"""环形预处理插件共用的薄适配逻辑。"""

from typing import Any, Mapping

import cv2
import numpy as np

from tool_defect.data.ring_geometry import process_ring_image
from tool_defect.plugin_api import (
    FrameBundle,
    PluginError,
    PluginErrorCode,
    TransformRecord,
    classify_unexpected,
)
from tool_defect.plugin_api.transforms import (
    affine_transform_record,
    polar_transform_record,
)


def primary_bgr_frame(frames: FrameBundle):
    candidates = [
        frame
        for frame in frames.frames
        if frame.attributes.get("image_role", "primary") == "primary"
    ]
    if len(candidates) != 1:
        raise PluginError.create(
            PluginErrorCode.INPUT_INVALID,
            "decode",
            "预处理要求且只允许一张主图",
            {"primary_frames": len(candidates)},
        )
    frame = candidates[0]
    if frame.color_space != "BGR" or frame.pixels.shape[2] != 3:
        raise PluginError.create(
            PluginErrorCode.INPUT_INVALID,
            "decode",
            "当前环形预处理只接受 BGR 三通道图像",
        )
    return frame


def process_ring(frame, config: Mapping[str, Any]):
    try:
        return process_ring_image(
            frame.pixels,
            output_size=int(config["geometry_output_size"]),
            angle_samples=int(config["angle_samples"]),
        )
    except (ValueError, cv2.error) as error:
        raise PluginError.create(
            PluginErrorCode.PREPROCESS_REJECTED,
            "preprocess",
            "无法可靠定位刀具环形区域",
            {"exception_type": type(error).__name__},
        ) from error
    except Exception as error:
        raise classify_unexpected(error, "preprocess") from error


def gray_model_tensor(
    bgr: np.ndarray,
    output_height: int,
    output_width: int,
) -> np.ndarray:
    if bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
        raise ValueError("灰度缩放输入必须是 uint8 BGR 图像")
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(
        gray,
        (int(output_width), int(output_height)),
        # 现有训练与命令行推理固定使用 INTER_AREA；即使放大也必须
        # 保持该像素路径，避免适配器改变历史模型输入。
        interpolation=cv2.INTER_AREA,
    )
    rgb = cv2.cvtColor(resized, cv2.COLOR_GRAY2RGB)
    return np.expand_dims(rgb.astype(np.float32) / 255.0, axis=0)


def legacy_gray_model_tensor(
    frame,
    output_height: int,
    output_width: int,
) -> np.ndarray:
    """保留历史 IMREAD_GRAYSCALE 解码路径，同时保持插件内存输入。"""

    if frame.encoded_bytes is None:
        return gray_model_tensor(
            frame.pixels, output_height, output_width
        )
    encoded = np.frombuffer(frame.encoded_bytes, dtype=np.uint8)
    grayscale = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if (
        grayscale is None
        or grayscale.shape
        != (frame.original_height, frame.original_width)
    ):
        raise PluginError.create(
            PluginErrorCode.INPUT_INVALID,
            "preprocess",
            "原始编码内容无法按历史灰度路径解码",
        )
    resized = cv2.resize(
        grayscale,
        (int(output_width), int(output_height)),
        interpolation=cv2.INTER_AREA,
    )
    rgb = cv2.cvtColor(resized, cv2.COLOR_GRAY2RGB)
    return np.expand_dims(rgb.astype(np.float32) / 255.0, axis=0)


def ring_artifacts(ring) -> dict[str, np.ndarray]:
    return {
        "raw_inner_boundary": ring.raw_inner_boundary.astype(np.float32),
        "raw_outer_boundary": ring.raw_outer_boundary.astype(np.float32),
        "inner_boundary": ring.inner_boundary.astype(np.float32),
        "outer_boundary": ring.outer_boundary.astype(np.float32),
        "rectification_matrix": ring.rectification_matrix.astype(np.float32),
        "rectified_shape": np.asarray(
            ring.corrected.shape[:2], dtype=np.int32
        ),
    }


def affine_record(frame, ring) -> TransformRecord:
    return affine_transform_record(
        ring.rectification_matrix,
        source_space="original",
        target_space="rectified",
        source_shape=frame.pixels.shape[:2],
        target_shape=ring.corrected.shape[:2],
    )


def polar_record(ring) -> TransformRecord:
    record = polar_transform_record(
        source_space="rectified",
        target_space="polar_normalized",
        center=(
            ring.corrected_outer_circle.x,
            ring.corrected_outer_circle.y,
        ),
        inner_boundary_key="inner_boundary",
        outer_boundary_key="outer_boundary",
        radial_samples=int(ring.polar_image.shape[0]),
        angle_samples=int(ring.polar_image.shape[1]),
    )
    parameters = dict(record.parameters)
    parameters["source_shape"] = list(ring.corrected.shape[:2])
    return TransformRecord(
        transform_type=record.transform_type,
        source_space=record.source_space,
        target_space=record.target_space,
        parameters=parameters,
        artifact_refs=record.artifact_refs,
        invertible=record.invertible,
        inverse_error_pixels=record.inverse_error_pixels,
    )


def resize_record(
    source_space: str,
    source_shape: tuple[int, int],
    target_shape: tuple[int, int],
) -> TransformRecord:
    return TransformRecord(
        transform_type="resize",
        source_space=source_space,
        target_space="model_input",
        parameters={
            "source_shape": list(source_shape),
            "target_shape": list(target_shape),
            "image_interpolation": "INTER_AREA",
            "mask_interpolation": "INTER_NEAREST",
        },
        artifact_refs={},
        invertible=True,
        inverse_error_pixels=1.0,
    )


def validate_common_config(config: Mapping[str, Any]) -> None:
    required = {
        "geometry_output_size",
        "angle_samples",
        "model_height",
        "model_width",
    }
    if set(config) != required:
        raise ValueError("环形预处理配置字段不完整或包含未知字段")
    for name in required:
        if (
            isinstance(config[name], bool)
            or not isinstance(config[name], int)
            or config[name] < 2
        ):
            raise ValueError(f"预处理配置必须为正整数：{name}")
    if config["geometry_output_size"] < 32:
        raise ValueError("geometry_output_size 必须至少为 32")
    if config["angle_samples"] < 32:
        raise ValueError("angle_samples 必须至少为 32")
