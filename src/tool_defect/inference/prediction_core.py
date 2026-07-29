"""不执行文件读写的模型输出规范化纯函数。"""

from typing import Any, Mapping

import numpy as np

from tool_defect.plugin_api import AlgorithmOutcome, AlgorithmOutput
from tool_defect.plugin_api.validation import validate_algorithm_output


def named_model_outputs(
    model: Any,
    tensor: np.ndarray,
) -> Mapping[str, np.ndarray]:
    try:
        predictions = model.predict(tensor, verbose=0)
    except TypeError:
        predictions = model.predict(tensor)
    if isinstance(predictions, (list, tuple)):
        if len(predictions) != len(model.output_names):
            raise ValueError("模型输出数量与输出名称不一致")
        return {
            name: np.asarray(value)
            for name, value in zip(model.output_names, predictions)
        }
    if len(model.output_names) != 1:
        raise ValueError("多输出模型没有返回输出列表")
    return {model.output_names[0]: np.asarray(predictions)}


def normalize_classification_output(
    probabilities: np.ndarray,
    label_map: Mapping[int, str],
) -> AlgorithmOutput:
    values = _single_probability_row(probabilities)
    labels = _normalized_label_map(label_map)
    if len(values) != len(labels):
        raise ValueError("分类概率数量与类别映射不一致")
    class_probabilities = {
        labels[index]: float(value) for index, value in enumerate(values)
    }
    selected = labels[int(np.argmax(values))]
    outcome = _label_to_outcome(selected)
    output = AlgorithmOutput(
        outcome=outcome,
        class_probabilities=class_probabilities,
        masks={},
        regions=(),
        scores={"classification_confidence": float(np.max(values))},
        warnings=(),
        metadata={
            "label_map": {
                str(index): label for index, label in labels.items()
            },
            "mask_coordinate_spaces": {},
        },
    )
    validate_algorithm_output(output)
    return output


def normalize_multitask_outputs(
    outputs: Mapping[str, np.ndarray],
    label_map: Mapping[int, str],
    *,
    coordinate_space: str,
) -> AlgorithmOutput:
    required = {"cla_out", "seg_out"}
    missing = required.difference(outputs)
    if missing:
        raise ValueError("双任务模型缺少输出：" + ", ".join(sorted(missing)))
    classification = normalize_classification_output(
        outputs["cla_out"], label_map
    )
    segmentation = np.asarray(outputs["seg_out"])
    if segmentation.ndim != 4 or segmentation.shape[0] != 1:
        raise ValueError("分割输出必须是批量大小为 1 的四维数组")
    if segmentation.shape[-1] != 2:
        raise ValueError("分割输出必须包含背景和缺陷两个通道")
    if not np.all(np.isfinite(segmentation)):
        raise ValueError("分割输出包含非有限值")
    mask = np.argmax(segmentation[0], axis=-1).astype(np.uint8)
    warnings = list(classification.warnings)
    if (
        classification.outcome == AlgorithmOutcome.UNQUALIFIED
        and not np.any(mask)
    ):
        warnings.append("UNQUALIFIED_EMPTY_MASK")
    output = AlgorithmOutput(
        outcome=classification.outcome,
        class_probabilities=classification.class_probabilities,
        masks={"defect": mask},
        regions=(),
        scores=classification.scores,
        warnings=tuple(warnings),
        metadata={
            "label_map": {
                str(index): label
                for index, label in _normalized_label_map(
                    label_map
                ).items()
            },
            "mask_coordinate_spaces": {"defect": coordinate_space},
        },
    )
    validate_algorithm_output(output)
    return output


def _single_probability_row(probabilities: np.ndarray) -> np.ndarray:
    values = np.asarray(probabilities, dtype=np.float64)
    if values.ndim == 2 and values.shape[0] == 1:
        values = values[0]
    if values.ndim != 1 or not values.size:
        raise ValueError("分类输出必须是一条非空概率向量")
    if not np.all(np.isfinite(values)):
        raise ValueError("分类输出包含非有限值")
    return values


def _normalized_label_map(
    label_map: Mapping[int, str],
) -> dict[int, str]:
    result = {int(index): str(label) for index, label in label_map.items()}
    if sorted(result) != list(range(len(result))):
        raise ValueError("类别映射索引必须从 0 连续递增")
    if set(result.values()) != {"qualified", "unqualified"}:
        raise ValueError("当前二分类模型类别必须为 qualified 和 unqualified")
    return result


def _label_to_outcome(label: str) -> AlgorithmOutcome:
    if label == "qualified":
        return AlgorithmOutcome.QUALIFIED
    if label == "unqualified":
        return AlgorithmOutcome.UNQUALIFIED
    raise ValueError(f"未知算法类别：{label}")
