"""插件之间传递的严格内存对象。"""

from dataclasses import dataclass
import hashlib
import re
from types import MappingProxyType
from typing import Any, Mapping, Optional

import numpy as np

from tool_defect.plugin_api.enums import AlgorithmOutcome, QualityStatus


_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_COLOR_SPACES = {"BGR", "RGB", "GRAY"}


def readonly_array(value: np.ndarray) -> np.ndarray:
    array = np.ascontiguousarray(np.asarray(value)).copy()
    array.setflags(write=False)
    return array


def frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if any(not isinstance(key, str) for key in value):
        raise TypeError("插件内存映射键必须是字符串")
    return MappingProxyType(
        {
            key: _deep_freeze(nested)
            for key, nested in value.items()
        }
    )


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("插件内存嵌套映射键必须是字符串")
        return MappingProxyType(
            {
                key: _deep_freeze(nested)
                for key, nested in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(nested) for nested in value)
    if isinstance(value, np.ndarray):
        return readonly_array(value)
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not np.isfinite(value):
            raise ValueError("插件内存元数据浮点数必须是有限值")
        return value
    raise TypeError(
        "插件内存元数据包含不支持的类型："
        f"{type(value).__name__}"
    )


@dataclass(frozen=True)
class ImageFrame:
    image_id: str
    pixels: np.ndarray
    color_space: str
    media_type: str
    sha256: str
    original_height: int
    original_width: int
    attributes: Mapping[str, Any]
    encoded_bytes: bytes | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.image_id, str) or not self.image_id:
            raise TypeError("原始帧标识必须是非空字符串")
        if (
            not isinstance(self.media_type, str)
            or not self.media_type.startswith("image/")
        ):
            raise TypeError("原始帧媒体类型必须是图片")
        if not isinstance(self.sha256, str):
            raise TypeError("原始帧 SHA-256 必须是字符串")
        if not isinstance(self.attributes, Mapping):
            raise TypeError("原始帧属性必须是映射")
        if not isinstance(self.color_space, str):
            raise TypeError("原始帧色彩空间必须是字符串")
        if not isinstance(self.pixels, np.ndarray):
            raise TypeError("原始帧像素必须是 numpy 数组")
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (self.original_height, self.original_width)
        ):
            raise TypeError("原始帧尺寸必须是整数")
        pixels = readonly_array(self.pixels)
        if pixels.dtype != np.uint8:
            raise ValueError("原始帧像素必须是 uint8")
        if pixels.ndim != 3 or pixels.shape[2] not in (1, 3):
            raise ValueError("原始帧必须是 H x W x C 且通道数为 1 或 3")
        if not pixels.size:
            raise ValueError("原始帧不能为空")
        if self.color_space not in _COLOR_SPACES:
            raise ValueError(f"未知色彩空间：{self.color_space}")
        expected_channels = 1 if self.color_space == "GRAY" else 3
        if pixels.shape[2] != expected_channels:
            raise ValueError("像素通道数与声明色彩空间不一致")
        if pixels.shape[:2] != (self.original_height, self.original_width):
            raise ValueError("原始尺寸与像素数组不一致")
        if _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("原始帧 SHA-256 格式非法")
        if self.encoded_bytes is not None:
            if (
                not isinstance(self.encoded_bytes, bytes)
                or not self.encoded_bytes
            ):
                raise TypeError("原始编码内容必须是非空不可变字节串")
            encoded_sha256 = hashlib.sha256(
                self.encoded_bytes
            ).hexdigest()
            if encoded_sha256 != self.sha256.removeprefix("sha256:"):
                raise ValueError("原始编码内容与声明 SHA-256 不一致")
        object.__setattr__(self, "pixels", pixels)
        object.__setattr__(self, "attributes", frozen_mapping(self.attributes))


@dataclass(frozen=True)
class FrameBundle:
    capture_id: str
    frames: tuple[ImageFrame, ...]
    recipe_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.frames, tuple):
            raise TypeError("帧集合必须是不可变元组")
        if any(
            not isinstance(value, str) or not value
            for value in (self.capture_id, self.recipe_id)
        ):
            raise ValueError("采集标识和配方标识不能为空")
        if not self.frames:
            raise ValueError("帧集合不能为空")
        if any(
            not isinstance(frame, ImageFrame) for frame in self.frames
        ):
            raise TypeError("帧集合只能包含 ImageFrame")
        identifiers = [frame.image_id for frame in self.frames]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("帧集合中存在重复 image_id")


@dataclass(frozen=True)
class TransformRecord:
    transform_type: str
    source_space: str
    target_space: str
    parameters: Mapping[str, Any]
    artifact_refs: Mapping[str, str]
    invertible: bool
    inverse_error_pixels: Optional[float] = None

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value
            for value in (
                self.transform_type,
                self.source_space,
                self.target_space,
            )
        ):
            raise ValueError("几何变换类型和坐标空间不能为空")
        if not isinstance(self.parameters, Mapping) or not isinstance(
            self.artifact_refs, Mapping
        ):
            raise TypeError("几何变换参数和制品引用必须是映射")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.artifact_refs.items()
        ):
            raise TypeError("几何变换制品引用必须是字符串映射")
        if not isinstance(self.invertible, bool):
            raise TypeError("几何变换可逆标记必须是布尔值")
        if self.inverse_error_pixels is not None and (
            isinstance(self.inverse_error_pixels, bool)
            or not isinstance(
                self.inverse_error_pixels, (int, float, np.number)
            )
            or not np.isfinite(float(self.inverse_error_pixels))
        ):
            raise TypeError("逆变换误差必须是有限数值")
        if self.inverse_error_pixels is not None and self.inverse_error_pixels < 0:
            raise ValueError("逆变换误差不能为负数")
        if self.invertible and self.inverse_error_pixels is None:
            object.__setattr__(self, "inverse_error_pixels", 0.0)
        object.__setattr__(self, "parameters", frozen_mapping(self.parameters))
        object.__setattr__(self, "artifact_refs", frozen_mapping(self.artifact_refs))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "transform_type": self.transform_type,
            "source_space": self.source_space,
            "target_space": self.target_space,
            "parameters": dict(self.parameters),
            "artifact_refs": dict(self.artifact_refs),
            "invertible": self.invertible,
            "inverse_error_pixels": self.inverse_error_pixels,
        }


@dataclass(frozen=True)
class PreparedBatch:
    tensors: Mapping[str, np.ndarray]
    coordinate_spaces: Mapping[str, Mapping[str, Any]]
    transforms: tuple[TransformRecord, ...]
    artifacts: Mapping[str, np.ndarray]
    quality_status: QualityStatus
    warnings: tuple[str, ...]
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.quality_status, QualityStatus):
            raise TypeError("预处理质量必须使用 QualityStatus 枚举")
        if not isinstance(self.transforms, tuple):
            raise TypeError("几何变换链必须是不可变元组")
        if any(
            not isinstance(transform, TransformRecord)
            for transform in self.transforms
        ):
            raise TypeError("几何变换链只能包含 TransformRecord")
        if not isinstance(self.warnings, tuple) or any(
            not isinstance(warning, str) for warning in self.warnings
        ):
            raise TypeError("预处理警告必须是字符串元组")
        for name, value in (
            ("tensors", self.tensors),
            ("coordinate_spaces", self.coordinate_spaces),
            ("artifacts", self.artifacts),
            ("metadata", self.metadata),
        ):
            if not isinstance(value, Mapping):
                raise TypeError(f"{name} 必须是映射")
        if any(
            not isinstance(name, str) or not name
            for name in (
                *self.tensors.keys(),
                *self.coordinate_spaces.keys(),
                *self.artifacts.keys(),
            )
        ):
            raise TypeError("张量、坐标空间和制品名称必须是非空字符串")
        if any(
            not isinstance(array, np.ndarray)
            for array in (*self.tensors.values(), *self.artifacts.values())
        ):
            raise TypeError("预处理张量和制品必须是 numpy 数组")
        if any(
            not isinstance(space, Mapping)
            for space in self.coordinate_spaces.values()
        ):
            raise TypeError("坐标空间定义必须是映射")
        tensors = {
            name: readonly_array(array)
            for name, array in self.tensors.items()
        }
        artifacts = {
            name: readonly_array(array)
            for name, array in self.artifacts.items()
        }
        coordinate_spaces = {
            name: frozen_mapping(space)
            for name, space in self.coordinate_spaces.items()
        }
        if self.quality_status != QualityStatus.REJECTED and not tensors:
            raise ValueError("可推理的预处理结果必须包含张量")
        missing_spaces = set(tensors).difference(coordinate_spaces)
        if missing_spaces:
            raise ValueError(
                "预处理张量缺少坐标空间：" + ", ".join(sorted(missing_spaces))
            )
        object.__setattr__(self, "tensors", MappingProxyType(tensors))
        object.__setattr__(self, "artifacts", MappingProxyType(artifacts))
        object.__setattr__(
            self, "coordinate_spaces", MappingProxyType(coordinate_spaces)
        )
        object.__setattr__(self, "metadata", frozen_mapping(self.metadata))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class AlgorithmOutput:
    outcome: AlgorithmOutcome
    class_probabilities: Mapping[str, float]
    masks: Mapping[str, np.ndarray]
    regions: tuple[Mapping[str, Any], ...]
    scores: Mapping[str, float]
    warnings: tuple[str, ...]
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, AlgorithmOutcome):
            raise TypeError("算法结论必须使用 AlgorithmOutcome 枚举")
        if not isinstance(self.regions, tuple):
            raise TypeError("算法区域必须是不可变元组")
        if not isinstance(self.warnings, tuple) or any(
            not isinstance(warning, str) for warning in self.warnings
        ):
            raise TypeError("算法警告必须是字符串元组")
        for name, value in (
            ("class_probabilities", self.class_probabilities),
            ("masks", self.masks),
            ("scores", self.scores),
            ("metadata", self.metadata),
        ):
            if not isinstance(value, Mapping):
                raise TypeError(f"{name} 必须是映射")
        if any(
            not isinstance(name, str) or not name
            for name in (
                *self.class_probabilities.keys(),
                *self.masks.keys(),
                *self.scores.keys(),
            )
        ):
            raise TypeError("算法概率、掩膜和分数名称必须是非空字符串")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float, np.number))
            for value in (
                *self.class_probabilities.values(),
                *self.scores.values(),
            )
        ):
            raise TypeError("算法概率和分数必须是数值")
        if any(
            not isinstance(mask, np.ndarray)
            for mask in self.masks.values()
        ):
            raise TypeError("算法掩膜必须是 numpy 数组")
        if any(
            not isinstance(region, Mapping) for region in self.regions
        ):
            raise TypeError("算法区域必须是映射")
        masks = {
            name: readonly_array(array)
            for name, array in self.masks.items()
        }
        regions = tuple(frozen_mapping(region) for region in self.regions)
        object.__setattr__(
            self,
            "class_probabilities",
            MappingProxyType(
                {
                    name: float(value)
                    for name, value in self.class_probabilities.items()
                }
            ),
        )
        object.__setattr__(self, "masks", MappingProxyType(masks))
        object.__setattr__(
            self,
            "scores",
            MappingProxyType(
                {name: float(value) for name, value in self.scores.items()}
            ),
        )
        object.__setattr__(self, "regions", regions)
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "metadata", frozen_mapping(self.metadata))
