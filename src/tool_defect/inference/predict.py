"""Inference using the supplied JSON/H5 artifacts."""

import csv
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from tool_defect.data.preprocess import (
    apply_input_preprocessing,
    artifact_preprocessing_mode,
)
from tool_defect.inference.input_pipeline import (
    RAW,
    aggregate_patch_masks,
    artifact_inference_mode,
    prepare_inference_input,
)
from tool_defect.inference.visualize import overlay_defect_on_image
from tool_defect.models.loader import load_saved_model


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
CLASS_NAMES = ("qualified", "unqualified")


def discover_images(input_paths):
    if isinstance(input_paths, (str, Path)):
        input_paths = [input_paths]
    image_list = []
    for item in input_paths:
        path = Path(item)
        if path.is_file():
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                raise ValueError(f"unsupported image file: {path}")
            image_list.append(path)
        elif path.is_dir():
            images = sorted(
                (
                    p
                    for p in path.rglob("*")
                    if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
                ),
                key=lambda p: str(p).lower(),
            )
            image_list.extend(images)
        else:
            raise ValueError(f"no supported images found: {path}")
    if not image_list:
        raise ValueError(f"no supported images found in: {input_paths}")
    return image_list


def _named_predictions(model, predictions):
    if not isinstance(predictions, (list, tuple)):
        return {model.output_names[0]: predictions}
    return dict(zip(model.output_names, predictions))


def _write_png(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise OSError(f"unable to encode predicted mask: {path}")
    encoded.tofile(path)


def _localization_overlay(ring_result):
    """Draw the detected outer/inner ellipses and center on the source image."""

    overlay = ring_result.source.copy()
    line_width = max(2, int(round(min(overlay.shape[:2]) / 300)))
    for ellipse, color in (
        (ring_result.outer_ellipse, (0, 220, 0)),
        (ring_result.inner_ellipse, (0, 0, 255)),
    ):
        cv2.ellipse(
            overlay,
            (int(round(ellipse.x)), int(round(ellipse.y))),
            (
                int(round(ellipse.major_radius)),
                int(round(ellipse.minor_radius)),
            ),
            ellipse.angle,
            0,
            360,
            color,
            line_width,
            cv2.LINE_AA,
        )
    cv2.drawMarker(
        overlay,
        (
            int(round(ring_result.outer_ellipse.x)),
            int(round(ring_result.outer_ellipse.y)),
        ),
        (255, 0, 255),
        cv2.MARKER_CROSS,
        max(12, line_width * 5),
        line_width,
    )
    max_dimension = 1600
    height, width = overlay.shape[:2]
    if max(height, width) > max_dimension:
        scale = max_dimension / float(max(height, width))
        overlay = cv2.resize(
            overlay,
            (
                max(1, int(round(width * scale))),
                max(1, int(round(height * scale))),
            ),
            interpolation=cv2.INTER_AREA,
        )
    return overlay


def _classification_probabilities(class_output, patch_count):
    probabilities = np.asarray(class_output, dtype=np.float32)
    if probabilities.ndim != 2 or probabilities.shape[1] != 2:
        raise ValueError(
            f"分类输出必须是 Nx2 概率，实际为 {probabilities.shape}"
        )
    if int(patch_count) == 1:
        return probabilities[0]
    # 八分块是“任意一块有缺陷，整片按不合格处理”，因此父图概率取
    # 各块不合格概率的最大值；合格概率保持二分类概率和为 1。
    unqualified_probability = float(np.max(probabilities[:, 1]))
    return np.asarray(
        [1.0 - unqualified_probability, unqualified_probability],
        dtype=np.float32,
    )


def _segmentation_mask(named, prepared):
    segmentation = np.asarray(named["seg_out"])
    patch_masks = (np.argmax(segmentation, axis=-1) * 255).astype(np.uint8)
    if patch_masks.shape[0] == 1:
        return patch_masks[0]
    return aggregate_patch_masks(
        patch_masks,
        prepared.display_image,
        prepared.mode,
    )


def _failed_row(
    image_path,
    mode,
    error,
    *,
    localization_status="failed",
    inference_status="localization_failed",
    localization_path="",
):
    return {
        "image_path": str(image_path),
        "inference_mode": mode,
        "localization_status": localization_status,
        "localization_path": localization_path,
        "inference_status": inference_status,
        "decision": "manual_review",
        "predicted_label": "",
        "predicted_class": "manual_review",
        "qualified_probability": "",
        "unqualified_probability": "",
        "mask_path": "",
        "visualization_path": "",
        "error": str(error),
    }


def predict(task, input_paths, output_dir, model_dir, image_size=None):
    if task not in {"classification", "multitask"}:
        raise ValueError("task must be 'classification' or 'multitask'")

    images = discover_images(input_paths)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    localization_dir = output_dir / "localizations"
    localization_dir.mkdir(parents=True, exist_ok=True)
    mask_dir = output_dir / "masks"
    visualization_dir = output_dir / "visualizations"
    if task == "multitask":
        mask_dir.mkdir(parents=True, exist_ok=True)
        visualization_dir.mkdir(parents=True, exist_ok=True)

    model = load_saved_model(model_dir)
    preprocessing = artifact_preprocessing_mode(model_dir)
    inference_mode = artifact_inference_mode(model_dir)
    model_image_size = int(model.input_shape[1])
    if image_size is not None and int(image_size) != model_image_size:
        raise ValueError(
            f"requested image size {image_size} does not match model input "
            f"{model_image_size}"
        )
    rows = []
    for index, image_path in enumerate(images):
        try:
            if inference_mode == RAW:
                # 旧 raw 模型仍保持原输入坐标，定位结果用于校验和留证；
                # 新的边界归一化模型则由 prepare_inference_input 真正使用定位结果。
                from tool_defect.data.ring_geometry import process_image_path

                ring_result = process_image_path(image_path)
                prepared = prepare_inference_input(
                    image_path,
                    inference_mode,
                    model_image_size,
                )
                prepared = replace(prepared, ring_result=ring_result)
            else:
                prepared = prepare_inference_input(
                    image_path,
                    inference_mode,
                    model_image_size,
                )
            localization_path_value = ""
            if prepared.ring_result is not None:
                localization_name = f"{index:04d}_{image_path.stem}_localization.png"
                localization_path = localization_dir / localization_name
                _write_png(
                    localization_path,
                    _localization_overlay(prepared.ring_result),
                )
                localization_path_value = (
                    Path("localizations") / localization_name
                ).as_posix()
        except Exception as error:
            row = _failed_row(image_path, inference_mode, error)
            rows.append(row)
            continue

        try:
            batch = apply_input_preprocessing(prepared.batches, preprocessing)
            named = _named_predictions(model, model.predict(batch, verbose=0))
            class_output_name = (
                "cla_out" if "cla_out" in named else model.output_names[0]
            )
            probabilities = _classification_probabilities(
                named[class_output_name],
                prepared.batches.shape[0],
            )
            predicted_index = int(np.argmax(probabilities))
            row = {
                "image_path": str(image_path),
                "inference_mode": inference_mode,
                "localization_status": "success",
                "localization_path": localization_path_value,
                "inference_status": "success",
                "decision": CLASS_NAMES[predicted_index],
                "predicted_label": predicted_index,
                "predicted_class": CLASS_NAMES[predicted_index],
                "qualified_probability": f"{float(probabilities[0]):.8f}",
                "unqualified_probability": f"{float(probabilities[1]):.8f}",
                "mask_path": "",
                "visualization_path": "",
                "error": "",
            }
            if task == "multitask":
                mask = _segmentation_mask(named, prepared)
                mask_name = f"{index:04d}_{image_path.stem}.png"
                mask_path = mask_dir / mask_name
                _write_png(mask_path, mask)
                row["mask_path"] = (Path("masks") / mask_name).as_posix()

                # 归一化模型的掩码和展示图必须处于同一展开坐标；旧 raw
                # 模型继续在原图上展示，避免把两个坐标系混用。
                confidence = float(probabilities[predicted_index])
                vis_name = f"{index:04d}_{image_path.stem}_result.png"
                vis_path = visualization_dir / vis_name
                overlay_defect_on_image(
                    original_path=(
                        image_path if prepared.display_image is None else None
                    ),
                    original_image=prepared.display_image,
                    defect_mask=mask,
                    predicted_class=CLASS_NAMES[predicted_index],
                    confidence=confidence,
                    output_path=vis_path,
                )
                row["visualization_path"] = (
                    Path("visualizations") / vis_name
                ).as_posix()
        except Exception as error:
            row = _failed_row(
                image_path,
                inference_mode,
                error,
                localization_status="success",
                inference_status="inference_failed",
                localization_path=localization_path_value,
            )
        rows.append(row)

    result_path = output_dir / "predictions.csv"
    with result_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "image_path",
                "inference_mode",
                "localization_status",
                "localization_path",
                "inference_status",
                "decision",
                "predicted_label",
                "predicted_class",
                "qualified_probability",
                "unqualified_probability",
                "mask_path",
                "visualization_path",
                "error",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return result_path
