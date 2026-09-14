"""Prepare raw microscope images for the project's trained model artifacts."""

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from tool_defect.data.circular_slice_dataset import (
    DEFAULT_SLICE_COUNT,
    DEFAULT_STRIDE_DEGREES,
    DEFAULT_WINDOW_DEGREES,
    annular_sector_mask,
    circular_slice,
)
from tool_defect.data.preprocess import load_image_batch
from tool_defect.data.ring_geometry import (
    RingResult,
    process_image_path,
    unwrap_annulus_normalized,
)


RAW = "raw"
ADAPTIVE_ANNULAR = "adaptive_annular"
ADAPTIVE_ANNULAR_8PATCH = "adaptive_annular_8patch"
BOUNDARY_NORMALIZED = "boundary_normalized"
BOUNDARY_NORMALIZED_8PATCH = "boundary_normalized_8patch"
SUPPORTED_MODES = {
    RAW,
    ADAPTIVE_ANNULAR,
    ADAPTIVE_ANNULAR_8PATCH,
    BOUNDARY_NORMALIZED,
    BOUNDARY_NORMALIZED_8PATCH,
}


@dataclass(frozen=True)
class PreparedInferenceInput:
    """One image converted to the same input coordinate system as training."""

    batches: np.ndarray
    display_image: Optional[np.ndarray]
    ring_result: Optional[RingResult]
    mode: str
    patch_starts: tuple[int, ...]


def inference_mode_from_data_path(data_path):
    """Infer the preprocessing mode used by a dataset path."""

    name = str(data_path).replace("\\", "/").lower().rstrip("/")
    if name.endswith("boundary_normalized_8patch") or "/boundary_normalized_8patch/" in name:
        return BOUNDARY_NORMALIZED_8PATCH
    if name.endswith("boundary_normalized") or "/boundary_normalized/" in name:
        return BOUNDARY_NORMALIZED
    if name.endswith("adaptive_annular_8patch") or "/adaptive_annular_8patch/" in name:
        return ADAPTIVE_ANNULAR_8PATCH
    if name.endswith("adaptive_annular") or "/adaptive_annular/" in name:
        return ADAPTIVE_ANNULAR
    return RAW


def artifact_inference_mode(model_dir):
    """Read the artifact mode, with a compatibility fallback for old runs."""

    model_dir = Path(model_dir)
    metadata_path = model_dir / "inference.json"
    if metadata_path.is_file():
        with metadata_path.open(encoding="utf-8") as handle:
            metadata = json.load(handle)
        mode = metadata.get("mode")
        if mode not in SUPPORTED_MODES:
            raise ValueError(
                f"invalid inference mode in {metadata_path}: {mode!r}"
            )
        return mode
    return inference_mode_from_data_path(model_dir.name)


def write_inference_metadata(model_dir, mode):
    """Persist the raw-image inference mode next to a trained artifact."""

    if mode not in SUPPORTED_MODES:
        raise ValueError(f"unsupported inference mode: {mode}")
    path = Path(model_dir) / "inference.json"
    path.write_text(
        json.dumps(
            {
                "mode": mode,
                "localization": "process_image_path for non-raw modes",
                "slice_count": DEFAULT_SLICE_COUNT,
                "window_degrees": DEFAULT_WINDOW_DEGREES,
                "stride_degrees": DEFAULT_STRIDE_DEGREES,
                "radial_samples": 256,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _as_model_batch(image, image_size):
    """Match load_image_batch: grayscale-to-RGB, square resize, [0, 1]."""

    image = np.asarray(image)
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim != 3 or image.shape[2] not in {3, 4}:
        raise ValueError("推理图像必须是灰度图或三/四通道彩色图")
    if image.shape[2] == 4:
        image = image[:, :, :3]
    resized = cv2.resize(
        image,
        (int(image_size), int(image_size)),
        interpolation=cv2.INTER_AREA,
    )
    return np.expand_dims(resized.astype(np.float32) / 255.0, axis=0)


def _boundary_patches(image):
    height, width = image.shape[:2]
    starts = tuple(
        int(round(index * width / DEFAULT_SLICE_COUNT))
        for index in range(DEFAULT_SLICE_COUNT)
    )
    patch_width = int(round(width * DEFAULT_WINDOW_DEGREES / 360.0))
    if patch_width < 1 or width < patch_width:
        raise ValueError(f"边界归一化图像宽度不适合八分块：{image.shape}")
    patches = tuple(
        circular_slice(image, start, patch_width) for start in starts
    )
    return patches, starts


def _adaptive_patches(image):
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    starts = tuple(
        int(round(index * DEFAULT_STRIDE_DEGREES))
        for index in range(DEFAULT_SLICE_COUNT)
    )
    patches = []
    for start in starts:
        sector = annular_sector_mask(
            image.shape[:2], center, start, DEFAULT_WINDOW_DEGREES
        )
        patch = image.copy()
        patch[~sector] = 0
        patches.append(patch)
    return tuple(patches), starts


def prepare_inference_input(image_path, mode, image_size):
    """Locate the ring and create one or eight model inputs."""

    if mode not in SUPPORTED_MODES:
        raise ValueError(f"unsupported inference mode: {mode}")
    if mode == RAW:
        return PreparedInferenceInput(
            batches=load_image_batch(image_path, image_size=image_size),
            display_image=None,
            ring_result=None,
            mode=mode,
            patch_starts=(),
        )

    ring_result = process_image_path(image_path)
    if mode in {BOUNDARY_NORMALIZED, BOUNDARY_NORMALIZED_8PATCH}:
        center = (
            ring_result.corrected_outer_circle.x,
            ring_result.corrected_outer_circle.y,
        )
        polar_image = unwrap_annulus_normalized(
            ring_result.corrected,
            center,
            ring_result.inner_boundary,
            ring_result.outer_boundary,
            radial_samples=int(image_size),
        )
        ring_result = replace(ring_result, polar_image=polar_image)
        base_image = ring_result.polar_image
    else:
        base_image = ring_result.annular_roi

    if mode in {BOUNDARY_NORMALIZED_8PATCH, ADAPTIVE_ANNULAR_8PATCH}:
        if mode == BOUNDARY_NORMALIZED_8PATCH:
            images, starts = _boundary_patches(base_image)
        else:
            images, starts = _adaptive_patches(base_image)
    else:
        images, starts = (base_image,), ()

    batches = np.concatenate(
        [_as_model_batch(image, image_size) for image in images],
        axis=0,
    )
    return PreparedInferenceInput(
        batches=batches,
        display_image=base_image,
        ring_result=ring_result,
        mode=mode,
        patch_starts=starts,
    )


def aggregate_patch_masks(patch_masks, base_image, mode):
    """Merge eight patch masks back into their model input coordinates."""

    if mode not in {BOUNDARY_NORMALIZED_8PATCH, ADAPTIVE_ANNULAR_8PATCH}:
        raise ValueError(f"not an eight-patch mode: {mode}")
    patch_masks = np.asarray(patch_masks)
    if patch_masks.ndim != 3 or patch_masks.shape[0] != DEFAULT_SLICE_COUNT:
        raise ValueError("八分块掩码必须是 8xHxW")
    height, width = base_image.shape[:2]
    merged = np.zeros((height, width), dtype=np.uint8)
    if mode == BOUNDARY_NORMALIZED_8PATCH:
        patch_width = int(round(width * DEFAULT_WINDOW_DEGREES / 360.0))
        starts = tuple(
            int(round(index * width / DEFAULT_SLICE_COUNT))
            for index in range(DEFAULT_SLICE_COUNT)
        )
        for patch_mask, start in zip(patch_masks, starts):
            resized = cv2.resize(
                patch_mask,
                (patch_width, height),
                interpolation=cv2.INTER_NEAREST,
            )
            columns = (np.arange(start, start + patch_width) % width).astype(
                np.intp
            )
            merged[:, columns] = np.maximum(merged[:, columns], resized)
    else:
        center = (width / 2.0, height / 2.0)
        for index, patch_mask in enumerate(patch_masks):
            resized = cv2.resize(
                patch_mask,
                (width, height),
                interpolation=cv2.INTER_NEAREST,
            )
            sector = annular_sector_mask(
                (height, width),
                center,
                index * DEFAULT_STRIDE_DEGREES,
                DEFAULT_WINDOW_DEGREES,
            )
            merged[sector] = np.maximum(merged[sector], resized[sector])
    return np.where(merged > 0, 255, 0).astype(np.uint8)
