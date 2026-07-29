"""把插件输出转换为无大数组的标准结果草稿。"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from tool_defect.plugin_api import (
    AlgorithmOutput,
    PreparedBatch,
    validate_algorithm_output,
    validate_prepared_batch,
)
from tool_defect.plugin_api.transforms import map_mask_to_original


@dataclass(frozen=True)
class DerivedArtifact:
    kind: str
    pixels: np.ndarray
    coordinate_space: str
    media_type: str


@dataclass(frozen=True)
class NormalizedResult:
    payload: Mapping[str, Any]
    artifacts: Mapping[str, DerivedArtifact]


def normalize_result(
    prepared: PreparedBatch,
    output: AlgorithmOutput,
) -> NormalizedResult:
    validate_prepared_batch(prepared)
    validate_algorithm_output(output)
    artifacts: dict[str, DerivedArtifact] = {}
    mask_spaces = dict(output.metadata.get("mask_coordinate_spaces", {}))
    for name, mask in output.masks.items():
        coordinate_space = mask_spaces[name]
        original = map_mask_to_original(
            mask,
            coordinate_space,
            prepared.transforms,
            prepared.artifacts,
        )
        artifacts[name] = DerivedArtifact(
            kind="DEFECT_MASK",
            pixels=original,
            coordinate_space="original",
            media_type="image/png",
        )
    probabilities = dict(output.class_probabilities)
    if probabilities:
        if set(probabilities) != {"qualified", "unqualified"}:
            raise ValueError("标准结果只接受冻结的二分类概率字段")
        confidence = max(probabilities.values())
    else:
        # 冻结网络契约要求两个概率字段始终存在；无分类头时使用中性分布，
        # confidence 保持 null，防止把占位值解释为模型置信度。
        probabilities = {"qualified": 0.5, "unqualified": 0.5}
        confidence = None
    payload = {
        "algorithm_outcome": output.outcome.value,
        "confidence": confidence,
        "class_probabilities": probabilities,
        "regions": [_normalize_region(region) for region in output.regions],
        "warnings": list(prepared.warnings) + list(output.warnings),
        "artifacts_pending": [
            {"name": name, "kind": artifact.kind}
            for name, artifact in artifacts.items()
        ],
    }
    return NormalizedResult(
        payload=MappingProxyType(payload),
        artifacts=MappingProxyType(artifacts),
    )


_COORDINATE_SPACES = {
    "original": "ORIGINAL",
    "ORIGINAL": "ORIGINAL",
    "model": "MODEL",
    "model_input": "MODEL",
    "MODEL": "MODEL",
    "polar": "POLAR",
    "polar_normalized": "POLAR",
    "POLAR": "POLAR",
}
_GEOMETRY_TYPES = {
    "mask_ref": "MASK_REF",
    "MASK_REF": "MASK_REF",
    "polygon": "POLYGON",
    "POLYGON": "POLYGON",
    "bbox": "BBOX",
    "BBOX": "BBOX",
    "polar_interval": "POLAR_INTERVAL",
    "POLAR_INTERVAL": "POLAR_INTERVAL",
}
_GEOMETRY_FIELDS = {
    "MASK_REF": {"image_id"},
    "POLYGON": {"points"},
    "BBOX": {"x", "y", "width", "height"},
    "POLAR_INTERVAL": {
        "angle_start_degrees",
        "angle_end_degrees",
        "radial_start",
        "radial_end",
    },
}


def _normalize_region(region: Mapping[str, Any]) -> dict[str, Any]:
    try:
        coordinate_space = _COORDINATE_SPACES[region["coordinate_space"]]
        geometry_type = _GEOMETRY_TYPES[region["geometry_type"]]
        region_id = int(region["region_id"])
        geometry = dict(region["geometry"])
        scores = {
            str(name): float(value)
            for name, value in dict(region["scores"]).items()
        }
        attributes = {
            str(name): _json_scalar(value)
            for name, value in dict(region["attributes"]).items()
        }
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("算法区域无法转换为冻结结果契约") from error
    if geometry_type == "POLAR_INTERVAL":
        aliases = {
            "start_angle_degrees": "angle_start_degrees",
            "end_angle_degrees": "angle_end_degrees",
        }
        geometry = {
            aliases.get(str(name), str(name)): _json_value(value)
            for name, value in geometry.items()
        }
    else:
        geometry = {
            str(name): _json_value(value)
            for name, value in geometry.items()
        }
    if (
        region_id < 1
        or set(geometry) != _GEOMETRY_FIELDS[geometry_type]
        or not _geometry_is_valid(geometry_type, geometry)
        or len(scores) > 16
        or len(attributes) > 32
        or any(
            not np.isfinite(value) or value < 0.0 or value > 1.0
            for value in scores.values()
        )
    ):
        raise ValueError("算法区域超出冻结结果契约约束")
    return {
        "region_id": region_id,
        "coordinate_space": coordinate_space,
        "geometry_type": geometry_type,
        "geometry": geometry,
        "scores": scores,
        "attributes": attributes,
    }


def _geometry_is_valid(
    geometry_type: str,
    geometry: Mapping[str, Any],
) -> bool:
    if geometry_type == "MASK_REF":
        return isinstance(geometry["image_id"], str) and bool(
            geometry["image_id"]
        )
    if geometry_type == "BBOX":
        return all(
            isinstance(geometry[name], (int, float))
            and not isinstance(geometry[name], bool)
            and np.isfinite(float(geometry[name]))
            and float(geometry[name]) >= 0.0
            for name in ("x", "y", "width", "height")
        )
    if geometry_type == "POLYGON":
        points = geometry["points"]
        return (
            isinstance(points, list)
            and 3 <= len(points) <= 128
            and all(
                isinstance(point, list)
                and len(point) == 2
                and all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and np.isfinite(float(value))
                    for value in point
                )
                for point in points
            )
        )
    return all(
        isinstance(geometry[name], (int, float))
        and not isinstance(geometry[name], bool)
        and np.isfinite(float(geometry[name]))
        and 0.0 <= float(geometry[name]) <= upper
        for name, upper in (
            ("angle_start_degrees", 360.0),
            ("angle_end_degrees", 360.0),
            ("radial_start", 1.0),
            ("radial_end", 1.0),
        )
    )


def _json_scalar(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and np.isfinite(value):
        return value
    raise TypeError("区域属性必须是有限 JSON 标量")


def _json_value(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and np.isfinite(value):
        return value
    if isinstance(value, str):
        return value
    raise TypeError("区域几何必须由有限 JSON 值组成")
