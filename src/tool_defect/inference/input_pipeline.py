"""Prepare raw circular blades with the same geometry used for training."""

from dataclasses import dataclass
import json
from pathlib import Path

import cv2
import numpy as np

from tool_defect.data.circular_slice_dataset import (
    DEFAULT_SLICE_COUNT,
    DEFAULT_STRIDE_DEGREES,
    DEFAULT_WINDOW_DEGREES,
    _validate_geometry,
    circular_slice,
)
from tool_defect.data.preprocess import load_grayscale_array
from tool_defect.data.ring_dataset import normalize_boundary_image
from tool_defect.data.ring_geometry import process_image_path


RAW_INPUT = "raw"
BOUNDARY_NORMALIZED_INPUT = "boundary-normalized"
BOUNDARY_NORMALIZED_8PATCH_INPUT = "boundary-normalized-8patch"
AUTO_INPUT = "auto"


def resolve_input_mode(requested_mode, configured_data_root):
    """Infer the expected input transform from the selected dataset config."""

    if requested_mode != AUTO_INPUT:
        return requested_mode
    data_root = Path(configured_data_root)
    name = data_root.name.casefold()
    if name == "boundary_normalized_8patch":
        return BOUNDARY_NORMALIZED_8PATCH_INPUT
    if name == "boundary_normalized":
        return BOUNDARY_NORMALIZED_INPUT
    return RAW_INPUT


def load_ring_settings(configured_data_root, input_mode):
    """Load the exact preprocessing geometry recorded during dataset builds."""

    if input_mode == RAW_INPUT:
        return None
    data_root = Path(configured_data_root)
    if input_mode == BOUNDARY_NORMALIZED_8PATCH_INPUT:
        source_root = data_root.parent / "boundary_normalized"
    elif input_mode == BOUNDARY_NORMALIZED_INPUT:
        source_root = data_root
    else:
        raise ValueError(f"不支持的推理输入模式：{input_mode}")

    generation_path = source_root / "generation_report.json"
    if not generation_path.is_file():
        raise FileNotFoundError(
            f"找不到边界归一化数据集生成参数：{generation_path}"
        )
    with generation_path.open(encoding="utf-8") as handle:
        generation = json.load(handle)
    required = ("output_size", "angle_samples", "radial_samples")
    missing = [name for name in required if generation.get(name) is None]
    if generation.get("status") != "complete" or missing:
        raise ValueError(
            "边界归一化数据集生成参数不完整："
            f"status={generation.get('status')!r}, missing={missing}"
        )
    settings = {name: int(generation[name]) for name in required}
    if input_mode == BOUNDARY_NORMALIZED_8PATCH_INPUT:
        patch_path = data_root / "generation_report.json"
        if not patch_path.is_file():
            raise FileNotFoundError(f"找不到八分块数据集生成参数：{patch_path}")
        with patch_path.open(encoding="utf-8") as handle:
            patch = json.load(handle)
        patch_required = ("slice_count", "window_degrees", "stride_degrees")
        patch_missing = [name for name in patch_required if patch.get(name) is None]
        if patch.get("status") != "complete" or patch_missing:
            raise ValueError(
                "八分块数据集生成参数不完整："
                f"status={patch.get('status')!r}, missing={patch_missing}"
            )
        settings.update(
            {
                "slice_count": int(patch["slice_count"]),
                "window_degrees": float(patch["window_degrees"]),
                "stride_degrees": float(patch["stride_degrees"]),
            }
        )
    return settings


@dataclass(frozen=True)
class InferenceInputContext:
    """Geometry needed to aggregate patches and map masks to the source image."""

    mode: str
    ring_result: object
    normalized_image: np.ndarray
    image_size: int
    radial_samples: int
    angle_samples: int
    slice_count: int = 1
    window_degrees: float = 360.0
    stride_degrees: float = 360.0


def prepare_input_batch(
    image_path,
    image_size,
    input_mode,
    ring_settings=None,
):
    """Return model-ready input and optional source-to-polar geometry."""

    from tool_defect.data.preprocess import load_image_batch

    if input_mode == RAW_INPUT:
        return load_image_batch(image_path, image_size), None
    if input_mode not in {
        BOUNDARY_NORMALIZED_INPUT,
        BOUNDARY_NORMALIZED_8PATCH_INPUT,
    }:
        raise ValueError(f"不支持的推理输入模式：{input_mode}")
    if ring_settings is None:
        raise ValueError("边界归一化推理缺少数据集生成参数")

    output_size = int(ring_settings["output_size"])
    angle_samples = int(ring_settings["angle_samples"])
    radial_samples = int(ring_settings["radial_samples"])
    ring_result = process_image_path(
        image_path,
        output_size=output_size,
        angle_samples=angle_samples,
    )
    normalized_image = normalize_boundary_image(
        ring_result.source,
        ring_result,
        radial_samples=radial_samples,
    )
    if normalized_image.shape[:2] != (radial_samples, angle_samples):
        raise ValueError(
            "边界归一化输出尺寸与训练配置不一致："
            f"期望 {(radial_samples, angle_samples)}，"
            f"实际 {normalized_image.shape[:2]}"
        )

    if input_mode == BOUNDARY_NORMALIZED_INPUT:
        grayscale = cv2.cvtColor(normalized_image, cv2.COLOR_BGR2GRAY)
        batch = np.expand_dims(
            load_grayscale_array(grayscale, image_size),
            axis=0,
        )
        return batch, InferenceInputContext(
            mode=input_mode,
            ring_result=ring_result,
            normalized_image=normalized_image,
            image_size=int(image_size),
            radial_samples=radial_samples,
            angle_samples=angle_samples,
        )

    slice_count = int(ring_settings.get("slice_count", DEFAULT_SLICE_COUNT))
    window_degrees = float(
        ring_settings.get("window_degrees", DEFAULT_WINDOW_DEGREES)
    )
    stride_degrees = float(
        ring_settings.get("stride_degrees", DEFAULT_STRIDE_DEGREES)
    )
    stride_columns, window_columns = _validate_geometry(
        angle_samples,
        slice_count,
        window_degrees,
        stride_degrees,
    )
    patches = []
    for patch_index in range(slice_count):
        patch = circular_slice(
            normalized_image,
            patch_index * stride_columns,
            window_columns,
        )
        grayscale = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        patches.append(load_grayscale_array(grayscale, image_size))
    return np.stack(patches), InferenceInputContext(
        mode=input_mode,
        ring_result=ring_result,
        normalized_image=normalized_image,
        image_size=int(image_size),
        radial_samples=radial_samples,
        angle_samples=angle_samples,
        slice_count=slice_count,
        window_degrees=window_degrees,
        stride_degrees=stride_degrees,
    )


def aggregate_class_probabilities(probabilities, context):
    """Aggregate overlapping patch classifications to the parent blade."""

    probabilities = np.asarray(probabilities, dtype=np.float32)
    if context.mode != BOUNDARY_NORMALIZED_8PATCH_INPUT:
        if probabilities.shape != (1, 2):
            raise ValueError(
                f"整图分类输出应为 (1, 2)，实际为 {probabilities.shape}"
            )
        return probabilities[0]
    if probabilities.shape != (context.slice_count, 2):
        raise ValueError(
            "八分块分类输出数量或形状错误："
            f"期望 {(context.slice_count, 2)}，实际 {probabilities.shape}"
        )
    unqualified_probability = float(np.max(probabilities[:, 1]))
    return np.asarray(
        [1.0 - unqualified_probability, unqualified_probability],
        dtype=np.float32,
    )


def _as_patch_parent_probability(segmentation, context):
    segmentation = np.asarray(segmentation, dtype=np.float32)
    if segmentation.ndim != 4 or segmentation.shape[0] != context.slice_count:
        raise ValueError(
            "八分块分割输出数量或维度错误："
            f"期望 {context.slice_count} 个 HxWxC 输出，实际 {segmentation.shape}"
        )
    stride_columns, window_columns = _validate_geometry(
        context.angle_samples,
        context.slice_count,
        context.window_degrees,
        context.stride_degrees,
    )
    parent_probability = np.zeros(
        (context.radial_samples, context.angle_samples),
        dtype=np.float32,
    )
    for patch_index, patch_segmentation in enumerate(segmentation):
        if patch_segmentation.ndim != 3 or patch_segmentation.shape[-1] < 2:
            raise ValueError("分割输出必须是 HxWx2 概率图")
        patch_probability = cv2.resize(
            patch_segmentation[..., 1],
            (window_columns, context.radial_samples),
            interpolation=cv2.INTER_LINEAR,
        )
        start_column = patch_index * stride_columns
        columns = (
            np.arange(start_column, start_column + window_columns)
            % context.angle_samples
        ).astype(np.intp)
        parent_probability[:, columns] = np.maximum(
            parent_probability[:, columns],
            patch_probability,
        )
    return parent_probability


def _to_source_probability(polar_probability, context):
    ring_result = context.ring_result
    corrected_height, corrected_width = ring_result.corrected.shape[:2]
    y, x = np.indices((corrected_height, corrected_width), dtype=np.float32)
    center = ring_result.corrected_outer_circle
    delta_x = x - float(center.x)
    delta_y = y - float(center.y)
    radius = np.sqrt(delta_x * delta_x + delta_y * delta_y)
    angle_position = (
        np.mod(np.arctan2(delta_y, delta_x), 2.0 * np.pi)
        * (context.angle_samples / (2.0 * np.pi))
    )
    lower_angle = np.floor(angle_position).astype(np.intp)
    upper_angle = (lower_angle + 1) % context.angle_samples
    angle_fraction = angle_position - lower_angle
    inner_boundary = (
        ring_result.inner_boundary[lower_angle] * (1.0 - angle_fraction)
        + ring_result.inner_boundary[upper_angle] * angle_fraction
    )
    outer_boundary = (
        ring_result.outer_boundary[lower_angle] * (1.0 - angle_fraction)
        + ring_result.outer_boundary[upper_angle] * angle_fraction
    )
    radial_position = (
        (outer_boundary - radius)
        / np.maximum(outer_boundary - inner_boundary, 1e-6)
        * (context.radial_samples - 1)
    )
    valid = (radius >= inner_boundary) & (radius <= outer_boundary)
    wrapped_probability = np.concatenate(
        [polar_probability, polar_probability[:, :1]],
        axis=1,
    )
    corrected_probability = cv2.remap(
        wrapped_probability,
        angle_position.astype(np.float32),
        radial_position.astype(np.float32),
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    corrected_probability[~valid] = 0.0

    source_height, source_width = ring_result.source.shape[:2]
    return cv2.warpAffine(
        corrected_probability,
        ring_result.rectification_matrix,
        (source_width, source_height),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def restore_defect_mask(segmentation, context):
    """Map model defect predictions back to the original source coordinates."""

    segmentation = np.asarray(segmentation, dtype=np.float32)
    if context.mode == BOUNDARY_NORMALIZED_8PATCH_INPUT:
        polar_probability = _as_patch_parent_probability(segmentation, context)
    else:
        if segmentation.ndim != 4 or segmentation.shape[0] != 1:
            raise ValueError(
                f"整图分割输出应为一个 HxWxC 概率图，实际为 {segmentation.shape}"
            )
        if segmentation.shape[-1] < 2:
            raise ValueError("分割输出必须包含背景和缺陷两个通道")
        polar_probability = cv2.resize(
            segmentation[0, ..., 1],
            (context.angle_samples, context.radial_samples),
            interpolation=cv2.INTER_LINEAR,
        )
    source_probability = _to_source_probability(polar_probability, context)
    return (source_probability >= 0.5).astype(np.uint8) * 255


def localization_overlay(context):
    """Draw detected outer and inner blade edges for inference auditing."""

    result = context.ring_result
    overlay = result.source.copy()
    for ellipse, color in (
        (result.outer_ellipse, (0, 220, 0)),
        (result.inner_ellipse, (0, 0, 255)),
    ):
        cv2.ellipse(
            overlay,
            (int(round(ellipse.x)), int(round(ellipse.y))),
            (
                max(1, int(round(ellipse.major_radius))),
                max(1, int(round(ellipse.minor_radius))),
            ),
            float(ellipse.angle),
            0,
            360,
            color,
            max(2, int(round(min(overlay.shape[:2]) / 300))),
            cv2.LINE_AA,
        )
    return overlay
