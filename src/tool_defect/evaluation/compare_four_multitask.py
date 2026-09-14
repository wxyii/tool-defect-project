"""统一比较甲乙两种初始化下的四组多任务模型。

主指标始终按父图统计。八分块模型通过 multitask_suite 中的溯源聚合逻辑
先合并子图分类与分割结果，再进入同一套分类、分割指标计算。
"""

import json
from pathlib import Path

import numpy as np

from tool_defect.evaluation.multitask_suite import (
    DatasetSpec,
    _load_dataset_result,
    _load_spec_paths,
    _reorder_result,
    _validate_data_inputs,
    _write_json,
    _write_model_outputs,
    artifact_status,
)


def _infer_parent_data_path(config_path):
    """Infer the complete preprocessed dataset from an ``*_8patch`` config."""

    with Path(config_path).open(encoding="utf-8") as handle:
        config = json.load(handle)
    data_path = Path(config["paths"]["data"])
    if not data_path.name.endswith("_8patch"):
        raise ValueError(
            "八分块配置的数据目录必须以 _8patch 结尾，"
            "或显式提供 patch_parent_data"
        )
    return data_path.with_name(data_path.name[: -len("_8patch")])


def build_four_group_specs(
    whole_config,
    whole_a,
    whole_b,
    patch_config,
    patch_a,
    patch_b,
    patch_parent_data=None,
):
    """Build the fixed A/B × whole/8-patch experiment specification."""

    parent_data = (
        Path(patch_parent_data)
        if patch_parent_data is not None
        else _infer_parent_data_path(patch_config)
    )
    return (
        DatasetSpec(
            "boundary_normalized_a",
            "甲：边界归一化完整",
            str(Path(whole_config)),
            str(Path(whole_a)),
            False,
        ),
        DatasetSpec(
            "boundary_normalized_b",
            "乙：边界归一化完整",
            str(Path(whole_config)),
            str(Path(whole_b)),
            False,
        ),
        DatasetSpec(
            "boundary_normalized_8patch_a",
            "甲：边界归一化八分块",
            str(Path(patch_config)),
            str(Path(patch_a)),
            True,
            str(parent_data),
        ),
        DatasetSpec(
            "boundary_normalized_8patch_b",
            "乙：边界归一化八分块",
            str(Path(patch_config)),
            str(Path(patch_b)),
            True,
            str(parent_data),
        ),
    )


def _initialization(spec):
    return "乙：ImageNet Xception 分阶段" if spec.dataset_id.endswith("_b") else "甲：原初始化"


def _with_group_metadata(spec, result, metrics):
    if int(metrics["samples"]) != len(result["parent_ids"]):
        raise ValueError(
            f"{spec.dataset_id} 主指标样本数不是父图数："
            f"metrics={metrics['samples']}，parents={len(result['parent_ids'])}"
        )
    metrics = dict(metrics)
    metrics.update(
        {
            "experiment_id": "乙" if spec.dataset_id.endswith("_b") else "甲",
            "initialization": _initialization(spec),
            "evaluation_level": "parent",
            "parent_samples": len(result["parent_ids"]),
            "patch_level_auxiliary_samples": int(
                result["patch_metrics"]["samples"]
            )
            if result["patch_metrics"] is not None
            else 0,
        }
    )
    return metrics


def _delta_metrics(a, b):
    fields = (
        "classification_accuracy",
        "unqualified_recall",
        "unqualified_f1",
        "defect_iou",
        "defect_dice",
        "defect_precision",
        "defect_recall",
    )
    deltas = {}
    for field in fields:
        if field.startswith("unqualified_"):
            metric_name = field[len("unqualified_") :]
            value_a = a["classification"]["unqualified"][metric_name]
            value_b = b["classification"]["unqualified"][metric_name]
        elif field.startswith("defect_"):
            value_a = a["segmentation"]["defect"][field[7:]]
            value_b = b["segmentation"]["defect"][field[7:]]
        else:
            value_a = a[field]
            value_b = b[field]
        deltas[field] = float(value_b - value_a)
    return deltas


def _write_four_group_report(output_root, summary):
    lines = [
        "# 甲乙四组多任务模型父图级测试集对比",
        "",
        f"- 测试父图数量：{summary['samples']}",
        f"- 分割固定阈值：{summary['fixed_segmentation_threshold']:.2f}",
        "- 分类与分割主指标均按父图统计；八分块子图指标仅作为辅助诊断。",
        "- 八分块父图聚合：子图不合格概率取最大值，分割概率映射回父图后逐像素取最大值。",
        "",
        "| 实验 | 数据集 | 分类准确率 | 不合格召回率 | 不合格F1 | 缺陷IoU | 缺陷Dice | 缺陷召回率 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary["groups"]:
        classification = item["classification"]
        defect = item["segmentation"]["defect"]
        lines.append(
            f"| {item['experiment_id']} | {item['dataset_name']} | "
            f"{item['classification_accuracy']:.4f} | "
            f"{classification['unqualified']['recall']:.4f} | "
            f"{classification['unqualified']['f1']:.4f} | "
            f"{defect['iou']:.4f} | {defect['dice']:.4f} | "
            f"{defect['recall']:.4f} |"
        )
    lines.extend(("", "## 乙相对甲的变化", ""))
    lines.extend(
        (
            "| 数据集 | 分类准确率变化 | 不合格召回率变化 | 缺陷Dice变化 |",
            "|---|---:|---:|---:|",
        )
    )
    for item in summary["deltas"]:
        delta = item["delta"]
        lines.append(
            f"| {item['dataset_name']} | {delta['classification_accuracy']:+.4f} | "
            f"{delta['unqualified_recall']:+.4f} | {delta['defect_dice']:+.4f} |"
        )
    (Path(output_root) / "FOUR_GROUP_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def compare_four_multitask(
    project_root,
    *,
    whole_config,
    whole_a,
    whole_b,
    patch_config,
    patch_a,
    patch_b,
    output_dir,
    patch_parent_data=None,
    split="test",
    threshold=0.5,
):
    """Evaluate four artifacts on one common parent-level split."""

    if not 0.0 <= float(threshold) <= 1.0:
        raise ValueError("threshold 必须位于 [0, 1] 范围内")
    project_root = Path(project_root).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    specs = build_four_group_specs(
        whole_config,
        whole_a,
        whole_b,
        patch_config,
        patch_a,
        patch_b,
        patch_parent_data,
    )

    loaded = []
    canonical_parent_ids = None
    canonical_labels = None
    for spec in specs:
        paths = _load_spec_paths(project_root, spec)
        data_errors = _validate_data_inputs(spec, paths, split)
        if data_errors:
            raise RuntimeError(
                f"{spec.dataset_id} 预检查失败：\n" + "\n".join(data_errors)
            )
        status = artifact_status(paths["artifact_dir"])
        if not status["complete"]:
            raise FileNotFoundError(
                f"{spec.dataset_id} 模型工件不完整：{status['missing']}"
            )
        result = _load_dataset_result(spec, paths, split)
        if canonical_parent_ids is None:
            canonical_parent_ids = list(result["parent_ids"])
            canonical_labels = result["true_labels"].copy()
        else:
            result = _reorder_result(result, canonical_parent_ids)
            if not np.array_equal(result["true_labels"], canonical_labels):
                raise ValueError(f"父图标签不一致：{spec.dataset_id}")
        if len(result["masks"]) != len(canonical_parent_ids):
            raise ValueError(f"父图数量不一致：{spec.dataset_id}")
        loaded.append((spec, paths, result))

    groups = []
    for spec, paths, result in loaded:
        metrics = _write_model_outputs(
            spec,
            result,
            output_dir / spec.dataset_id,
            split,
            threshold,
        )
        group = _with_group_metadata(spec, result, metrics)
        group["artifact_dir"] = str(paths["artifact_dir"])
        group["config"] = str(paths["config"])
        groups.append(group)

    by_dataset = {
        "边界归一化完整": (groups[0], groups[1]),
        "边界归一化八分块": (groups[2], groups[3]),
    }
    deltas = [
        {
            "dataset_name": dataset_name,
            "delta": _delta_metrics(group_a, group_b),
        }
        for dataset_name, (group_a, group_b) in by_dataset.items()
    ]
    summary = {
        "split": split,
        "samples": len(canonical_parent_ids or []),
        "parent_sample_ids": canonical_parent_ids or [],
        "same_parent_set": True,
        "evaluation_level": "parent",
        "fixed_segmentation_threshold": float(threshold),
        "groups": groups,
        "deltas": deltas,
        "test_set_used_for_threshold_selection": False,
    }
    _write_json(output_dir / "four_group_metrics.json", summary)
    _write_four_group_report(output_dir, summary)
    return summary
