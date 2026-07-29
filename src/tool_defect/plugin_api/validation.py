"""插件输入输出的安全边界校验。"""

from typing import Iterable

import numpy as np

from tool_defect.plugin_api.enums import (
    AlgorithmOutcome,
    PluginErrorCode,
    QualityStatus,
)
from tool_defect.plugin_api.errors import PluginError
from tool_defect.plugin_api.memory import AlgorithmOutput, PreparedBatch


def validate_prepared_batch(batch: PreparedBatch) -> None:
    if batch.quality_status == QualityStatus.REJECTED:
        return
    for name, tensor in batch.tensors.items():
        if not tensor.size:
            raise PluginError.create(
                PluginErrorCode.PLUGIN_BUG,
                "preprocess",
                "预处理插件返回空张量",
                {"tensor": name},
            )
        if np.issubdtype(tensor.dtype, np.floating) and not np.all(
            np.isfinite(tensor)
        ):
            raise PluginError.create(
                PluginErrorCode.PLUGIN_BUG,
                "preprocess",
                "预处理张量包含非有限值",
                {"tensor": name},
            )


def validate_algorithm_output(
    output: AlgorithmOutput,
    *,
    probability_tolerance: float = 1e-4,
) -> None:
    probabilities = output.class_probabilities
    if probabilities:
        values = np.asarray(list(probabilities.values()), dtype=np.float64)
        if not np.all(np.isfinite(values)):
            raise _invalid_output("分类概率包含非有限值")
        if np.any(values < 0.0) or np.any(values > 1.0):
            raise _invalid_output("分类概率超出 0 到 1")
        if abs(float(np.sum(values)) - 1.0) > probability_tolerance:
            raise _invalid_output("分类概率之和不为 1")
        expected = {
            "qualified": AlgorithmOutcome.QUALIFIED,
            "unqualified": AlgorithmOutcome.UNQUALIFIED,
        }
        predicted = max(probabilities, key=probabilities.get)
        if predicted in expected and output.outcome not in (
            expected[predicted],
            AlgorithmOutcome.INCONCLUSIVE,
        ):
            raise _invalid_output("分类概率与算法结论矛盾")

    mask_spaces = output.metadata.get("mask_coordinate_spaces", {})
    if not isinstance(mask_spaces, dict):
        try:
            mask_spaces = dict(mask_spaces)
        except (TypeError, ValueError) as error:
            raise _invalid_output("掩膜坐标空间声明非法") from error
    for name, mask in output.masks.items():
        if mask.ndim != 2 or not mask.size:
            raise _invalid_output("算法掩膜必须是非空二维数组", {"mask": name})
        if not (
            np.issubdtype(mask.dtype, np.bool_)
            or np.issubdtype(mask.dtype, np.integer)
            or np.issubdtype(mask.dtype, np.floating)
        ):
            raise _invalid_output("算法掩膜必须是数值或布尔数组", {"mask": name})
        if np.issubdtype(mask.dtype, np.floating) and not np.all(
            np.isfinite(mask)
        ):
            raise _invalid_output("算法掩膜包含非有限值", {"mask": name})
        if name not in mask_spaces:
            raise _invalid_output("算法掩膜缺少坐标空间", {"mask": name})
    for index, region in enumerate(output.regions):
        if "coordinate_space" not in region:
            raise _invalid_output(
                "缺陷区域缺少坐标空间", {"region_index": index}
            )
        if "geometry_type" not in region or "geometry" not in region:
            raise _invalid_output(
                "缺陷区域缺少几何定义", {"region_index": index}
            )

    score_values: Iterable[float] = output.scores.values()
    if any(not np.isfinite(float(value)) for value in score_values):
        raise _invalid_output("算法分数包含非有限值")


def inconclusive_output(*warnings: str) -> AlgorithmOutput:
    return AlgorithmOutput(
        outcome=AlgorithmOutcome.INCONCLUSIVE,
        class_probabilities={},
        masks={},
        regions=(),
        scores={},
        warnings=tuple(warnings),
        metadata={"mask_coordinate_spaces": {}},
    )


def _invalid_output(
    message: str,
    details: dict[str, object] | None = None,
) -> PluginError:
    return PluginError.create(
        PluginErrorCode.PLUGIN_BUG,
        "result_validation",
        message,
        details,
    )
