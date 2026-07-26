"""Inference using the supplied JSON/H5 artifacts."""

import csv
from pathlib import Path

import cv2
import numpy as np

from tool_defect.data.preprocess import load_image_batch
from tool_defect.inference.visualize import overlay_defect_on_image
from tool_defect.models.loader import load_saved_model


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
CLASS_NAMES = ("qualified", "unqualified")


def discover_images(input_path):
    input_path = Path(input_path)
    if input_path.is_file():
        if input_path.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError(f"unsupported image file: {input_path}")
        return [input_path]
    if input_path.is_dir():
        images = sorted(
            (
                path
                for path in input_path.rglob("*")
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            ),
            key=lambda path: str(path).lower(),
        )
        if images:
            return images
    raise ValueError(f"no supported images found: {input_path}")


def _named_predictions(model, predictions):
    if not isinstance(predictions, (list, tuple)):
        return {model.output_names[0]: predictions}
    return dict(zip(model.output_names, predictions))


def _write_png(path, image):
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise OSError(f"unable to encode predicted mask: {path}")
    encoded.tofile(path)


def predict(task, input_path, output_dir, model_dir, image_size=None):
    if task not in {"classification", "multitask"}:
        raise ValueError("task must be 'classification' or 'multitask'")

    images = discover_images(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    mask_dir = output_dir / "masks"
    visualization_dir = output_dir / "visualizations"
    if task == "multitask":
        mask_dir.mkdir(parents=True, exist_ok=True)
        visualization_dir.mkdir(parents=True, exist_ok=True)

    model = load_saved_model(model_dir)
    model_image_size = int(model.input_shape[1])
    if image_size is not None and int(image_size) != model_image_size:
        raise ValueError(
            f"requested image size {image_size} does not match model input "
            f"{model_image_size}"
        )
    rows = []
    for index, image_path in enumerate(images):
        batch = load_image_batch(image_path, image_size=model_image_size)
        named = _named_predictions(model, model.predict(batch, verbose=0))
        class_output_name = (
            "cla_out" if "cla_out" in named else model.output_names[0]
        )
        probabilities = np.asarray(named[class_output_name])[0]
        predicted_index = int(np.argmax(probabilities))
        row = {
            "image_path": str(image_path),
            "predicted_label": predicted_index,
            "predicted_class": CLASS_NAMES[predicted_index],
            "qualified_probability": f"{float(probabilities[0]):.8f}",
            "unqualified_probability": f"{float(probabilities[1]):.8f}",
            "mask_path": "",
        }

        if task == "multitask":
            segmentation = np.asarray(named["seg_out"])[0]
            mask = (np.argmax(segmentation, axis=-1) * 255).astype(np.uint8)
            mask_name = f"{index:04d}_{image_path.stem}.png"
            mask_path = mask_dir / mask_name
            _write_png(mask_path, mask)
            row["mask_path"] = (Path("masks") / mask_name).as_posix()

            # Generate overlay visualization
            confidence = float(probabilities[predicted_index])
            vis_name = f"{index:04d}_{image_path.stem}_result.png"
            vis_path = visualization_dir / vis_name
            try:
                overlay_defect_on_image(
                    original_path=image_path,
                    defect_mask=mask,
                    predicted_class=CLASS_NAMES[predicted_index],
                    confidence=confidence,
                    output_path=vis_path,
                )
            except Exception as error:
                raise RuntimeError(
                    f"failed to create visualization for {image_path}: {error}"
                ) from error
            row["visualization_path"] = (Path("visualizations") / vis_name).as_posix()
        else:
            row["visualization_path"] = ""
        rows.append(row)

    result_path = output_dir / "predictions.csv"
    with result_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "image_path",
                "predicted_label",
                "predicted_class",
                "qualified_probability",
                "unqualified_probability",
                "mask_path",
                "visualization_path",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return result_path
