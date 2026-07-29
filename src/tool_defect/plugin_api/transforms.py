"""可审计几何变换记录和掩膜回映。"""

from typing import Mapping

import cv2
import numpy as np

from tool_defect.plugin_api.memory import TransformRecord


def affine_transform_record(
    matrix: np.ndarray,
    *,
    source_space: str,
    target_space: str,
    source_shape: tuple[int, int],
    target_shape: tuple[int, int],
) -> TransformRecord:
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (2, 3):
        raise ValueError("仿射矩阵必须是 2 x 3")
    return TransformRecord(
        transform_type="affine",
        source_space=source_space,
        target_space=target_space,
        parameters={
            "matrix": matrix.tolist(),
            "source_shape": list(source_shape),
            "target_shape": list(target_shape),
        },
        artifact_refs={},
        invertible=True,
        inverse_error_pixels=0.5,
    )


def polar_transform_record(
    *,
    source_space: str,
    target_space: str,
    center: tuple[float, float],
    inner_boundary_key: str,
    outer_boundary_key: str,
    radial_samples: int,
    angle_samples: int,
) -> TransformRecord:
    return TransformRecord(
        transform_type="polar_normalized",
        source_space=source_space,
        target_space=target_space,
        parameters={
            "center": [float(center[0]), float(center[1])],
            "radial_samples": int(radial_samples),
            "angle_samples": int(angle_samples),
        },
        artifact_refs={
            "inner_boundary": inner_boundary_key,
            "outer_boundary": outer_boundary_key,
        },
        invertible=True,
        inverse_error_pixels=2.0,
    )


def map_mask_to_original(
    mask: np.ndarray,
    coordinate_space: str,
    transforms: tuple[TransformRecord, ...],
    artifacts: Mapping[str, np.ndarray],
) -> np.ndarray:
    current = (np.asarray(mask) > 0).astype(np.uint8) * 255
    current_space = coordinate_space
    remaining = list(transforms)
    while current_space != "original":
        candidates = [
            record
            for record in remaining
            if record.target_space == current_space
        ]
        if not candidates:
            raise ValueError(
                f"找不到从坐标空间 {current_space} 回到原图的变换"
            )
        record = candidates[-1]
        remaining.remove(record)
        if not record.invertible:
            raise ValueError(f"变换不可逆：{record.transform_type}")
        if record.transform_type == "resize":
            source_shape = tuple(record.parameters["source_shape"])
            current = cv2.resize(
                current,
                (int(source_shape[1]), int(source_shape[0])),
                interpolation=cv2.INTER_NEAREST,
            )
        elif record.transform_type == "polar_normalized":
            current = _polar_to_rectified(current, record, artifacts)
        elif record.transform_type == "affine":
            source_shape = tuple(record.parameters["source_shape"])
            inverse = cv2.invertAffineTransform(
                np.asarray(record.parameters["matrix"], dtype=np.float32)
            )
            current = cv2.warpAffine(
                current,
                inverse,
                (int(source_shape[1]), int(source_shape[0])),
                flags=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=0,
            )
        elif record.transform_type == "identity_mask":
            pass
        else:
            raise ValueError(f"不支持的逆变换：{record.transform_type}")
        current_space = record.source_space
    return current


def _polar_to_rectified(
    mask: np.ndarray,
    record: TransformRecord,
    artifacts: Mapping[str, np.ndarray],
) -> np.ndarray:
    inner = np.asarray(
        artifacts[record.artifact_refs["inner_boundary"]], dtype=np.float32
    )
    outer = np.asarray(
        artifacts[record.artifact_refs["outer_boundary"]], dtype=np.float32
    )
    if inner.shape != outer.shape or inner.ndim != 1:
        raise ValueError("极坐标内外边界数组不兼容")
    source_shape = record.parameters.get("source_shape")
    if source_shape is None:
        source_shape = artifacts["rectified_shape"].tolist()
    height, width = (int(source_shape[0]), int(source_shape[1]))
    center_x, center_y = record.parameters["center"]
    polar = cv2.resize(
        mask,
        (len(inner), int(record.parameters["radial_samples"])),
        interpolation=cv2.INTER_NEAREST,
    )
    ys, xs = np.where(polar > 0)
    result = np.zeros((height, width), dtype=np.uint8)
    if not len(xs):
        return result
    angles = 2.0 * np.pi * xs / len(inner)
    fraction = ys / max(polar.shape[0] - 1, 1)
    radii = outer[xs] - fraction * (outer[xs] - inner[xs])
    target_x = np.rint(center_x + radii * np.cos(angles)).astype(np.int64)
    target_y = np.rint(center_y + radii * np.sin(angles)).astype(np.int64)
    valid = (
        (target_x >= 0)
        & (target_x < width)
        & (target_y >= 0)
        & (target_y < height)
    )
    result[target_y[valid], target_x[valid]] = 255
    return cv2.dilate(result, np.ones((3, 3), dtype=np.uint8))
