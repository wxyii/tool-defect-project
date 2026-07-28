"""Paired comparison of original and retrained multitask artifacts."""

import csv
import json
from pathlib import Path

import numpy as np
import tensorflow as tf

from tool_defect.config import load_config
from tool_defect.data.datasets import load_dataset
from tool_defect.data.preprocess import (
    apply_input_preprocessing,
    artifact_preprocessing_mode,
)
from tool_defect.evaluation.evaluate import _save_confusion_matrix
from tool_defect.evaluation.metrics import (
    CLASS_NAMES,
    SEGMENT_NAMES,
    classification_metrics,
    segmentation_metrics,
)
from tool_defect.models.loader import load_saved_model


SCHOOL_REFERENCE = {
    "classification_accuracy": 0.9655,
    "classification_recall": 0.9375,
    "classification_loss": 0.1263,
    "multitask_mean_iou": 0.8626,
}


def _predict(model_dir, images):
    model = load_saved_model(model_dir)
    if model.output_names != ["cla_out", "seg_out"]:
        raise ValueError(f"unexpected multitask outputs: {model.output_names}")
    preprocessing = artifact_preprocessing_mode(model_dir)
    predictions = model.predict(
        apply_input_preprocessing(images, preprocessing),
        batch_size=2,
        verbose=0,
    )
    named = dict(zip(model.output_names, predictions))
    output = (
        np.asarray(named["cla_out"]),
        np.asarray(named["seg_out"]),
        int(model.input_shape[1]),
    )
    del model
    tf.keras.backend.clear_session()
    return output


def _summary(labels, masks, classification, segmentation):
    class_result, class_matrix = classification_metrics(
        np.argmax(labels, axis=-1), classification
    )
    segment_result, segment_matrix = segmentation_metrics(masks, segmentation)
    flat = {
        "classification_accuracy": class_result["accuracy"],
        "classification_loss": class_result["cross_entropy_loss"],
        "unqualified_precision": class_result["unqualified"]["precision"],
        "unqualified_recall": class_result["unqualified"]["recall"],
        "unqualified_f1": class_result["unqualified"]["f1"],
        "segmentation_loss": segment_result["cross_entropy_loss"],
        "defect_iou": segment_result["defect"]["iou"],
        "defect_dice": segment_result["defect"]["dice"],
        "defect_precision": segment_result["defect"]["precision"],
        "defect_recall": segment_result["defect"]["recall"],
        "mean_iou": segment_result["mean_iou"],
        "total_standardized_loss": (
            class_result["cross_entropy_loss"]
            + segment_result["cross_entropy_loss"]
        ),
    }
    return flat, class_result, segment_result, class_matrix, segment_matrix


def _sample_statistics(labels, masks, class_probabilities, seg_probabilities):
    true_class = np.argmax(labels, axis=-1)
    predicted_class = np.argmax(class_probabilities, axis=-1)
    class_loss = -np.sum(
        labels
        * np.log(np.clip(class_probabilities.astype(np.float64), 1e-7, 1.0)),
        axis=-1,
    )
    true_seg = np.argmax(masks, axis=-1)
    predicted_seg = np.argmax(seg_probabilities, axis=-1)
    matrices = []
    seg_losses = []
    for index in range(len(labels)):
        matrix = np.bincount(
            2 * true_seg[index].reshape(-1).astype(np.int64)
            + predicted_seg[index].reshape(-1).astype(np.int64),
            minlength=4,
        ).reshape(2, 2)
        matrices.append(matrix)
        seg_losses.append(
            -np.mean(
                np.sum(
                    masks[index]
                    * np.log(
                        np.clip(
                            seg_probabilities[index].astype(np.float64),
                            1e-7,
                            1.0,
                        )
                    ),
                    axis=-1,
                )
            )
        )
    return {
        "true_class": true_class,
        "class_correct": (true_class == predicted_class).astype(np.float64),
        "class_loss": class_loss,
        "unqualified_tp": (
            (true_class == 1) & (predicted_class == 1)
        ).astype(np.int64),
        "unqualified_fp": (
            (true_class == 0) & (predicted_class == 1)
        ).astype(np.int64),
        "unqualified_fn": (
            (true_class == 1) & (predicted_class == 0)
        ).astype(np.int64),
        "segmentation_matrix": np.asarray(matrices, dtype=np.int64),
        "segmentation_loss": np.asarray(seg_losses, dtype=np.float64),
    }


def _safe_ratio(numerator, denominator):
    return np.divide(
        numerator,
        denominator,
        out=np.zeros_like(np.asarray(numerator, dtype=np.float64)),
        where=np.asarray(denominator) != 0,
    )


def _bootstrap_values(statistics, indexes):
    class_accuracy = statistics["class_correct"][indexes].mean(axis=1)
    class_loss = statistics["class_loss"][indexes].mean(axis=1)
    true_positive = statistics["unqualified_tp"][indexes].sum(axis=1)
    false_positive = statistics["unqualified_fp"][indexes].sum(axis=1)
    false_negative = statistics["unqualified_fn"][indexes].sum(axis=1)
    class_precision = _safe_ratio(true_positive, true_positive + false_positive)
    class_recall = _safe_ratio(true_positive, true_positive + false_negative)
    class_f1 = _safe_ratio(
        2 * class_precision * class_recall, class_precision + class_recall
    )
    matrices = statistics["segmentation_matrix"][indexes].sum(axis=1)
    seg_loss = statistics["segmentation_loss"][indexes].mean(axis=1)
    defect_tp = matrices[:, 1, 1]
    defect_fp = matrices[:, 0, 1]
    defect_fn = matrices[:, 1, 0]
    defect_iou = _safe_ratio(defect_tp, defect_tp + defect_fp + defect_fn)
    defect_dice = _safe_ratio(
        2 * defect_tp, 2 * defect_tp + defect_fp + defect_fn
    )
    defect_precision = _safe_ratio(defect_tp, defect_tp + defect_fp)
    defect_recall = _safe_ratio(defect_tp, defect_tp + defect_fn)
    background_tp = matrices[:, 0, 0]
    background_iou = _safe_ratio(
        background_tp,
        background_tp + matrices[:, 1, 0] + matrices[:, 0, 1],
    )
    return {
        "classification_accuracy": class_accuracy,
        "classification_loss": class_loss,
        "unqualified_precision": class_precision,
        "unqualified_recall": class_recall,
        "unqualified_f1": class_f1,
        "segmentation_loss": seg_loss,
        "defect_iou": defect_iou,
        "defect_dice": defect_dice,
        "defect_precision": defect_precision,
        "defect_recall": defect_recall,
        "mean_iou": (background_iou + defect_iou) / 2,
        "total_standardized_loss": class_loss + seg_loss,
    }


def _paired_bootstrap(
    labels,
    masks,
    baseline_class,
    baseline_seg,
    candidate_class,
    candidate_seg,
    samples,
    seed,
):
    true_labels = np.argmax(labels, axis=-1)
    randomizer = np.random.default_rng(seed)
    class_indexes = [np.flatnonzero(true_labels == label) for label in (0, 1)]
    sampled = []
    for _ in range(int(samples)):
        parts = [
            randomizer.choice(indexes, size=len(indexes), replace=True)
            for indexes in class_indexes
            if len(indexes)
        ]
        row = np.concatenate(parts)
        randomizer.shuffle(row)
        sampled.append(row)
    indexes = np.asarray(sampled, dtype=np.int64)
    baseline = _bootstrap_values(
        _sample_statistics(labels, masks, baseline_class, baseline_seg), indexes
    )
    candidate = _bootstrap_values(
        _sample_statistics(labels, masks, candidate_class, candidate_seg),
        indexes,
    )
    return {
        name: {
            "lower": float(np.quantile(candidate[name] - values, 0.025)),
            "upper": float(np.quantile(candidate[name] - values, 0.975)),
        }
        for name, values in baseline.items()
    }


def _per_image_metrics(true_mask, probability):
    result, _ = segmentation_metrics(
        true_mask[None, ...], probability[None, ...]
    )
    return result["defect"]["iou"], result["defect"]["dice"]


def _write_predictions(
    rows,
    labels,
    masks,
    baseline_class,
    baseline_seg,
    candidate_class,
    candidate_seg,
    destination,
):
    fields = [
        "sample_id",
        "image_path",
        "true_class",
        "baseline_class",
        "baseline_unqualified_probability",
        "baseline_defect_iou",
        "baseline_defect_dice",
        "candidate_class",
        "candidate_unqualified_probability",
        "candidate_defect_iou",
        "candidate_defect_dice",
    ]
    with Path(destination).open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, row in enumerate(rows):
            baseline_iou, baseline_dice = _per_image_metrics(
                masks[index], baseline_seg[index]
            )
            candidate_iou, candidate_dice = _per_image_metrics(
                masks[index], candidate_seg[index]
            )
            writer.writerow(
                {
                    "sample_id": row["sample_id"],
                    "image_path": row["image_path"],
                    "true_class": CLASS_NAMES[int(np.argmax(labels[index]))],
                    "baseline_class": CLASS_NAMES[
                        int(np.argmax(baseline_class[index]))
                    ],
                    "baseline_unqualified_probability": (
                        f"{float(baseline_class[index, 1]):.8f}"
                    ),
                    "baseline_defect_iou": f"{baseline_iou:.8f}",
                    "baseline_defect_dice": f"{baseline_dice:.8f}",
                    "candidate_class": CLASS_NAMES[
                        int(np.argmax(candidate_class[index]))
                    ],
                    "candidate_unqualified_probability": (
                        f"{float(candidate_class[index, 1]):.8f}"
                    ),
                    "candidate_defect_iou": f"{candidate_iou:.8f}",
                    "candidate_defect_dice": f"{candidate_dice:.8f}",
                }
            )


def _report(result):
    baseline = result["baseline"]
    candidate = result["candidate"]
    delta = result["delta"]
    promotion = "通过" if result["promotion_gate"]["passed"] else "未通过"
    return f"""# 双任务模型同测试集对比

- 测试样本：{result['samples']}
- 推广门槛：{promotion}
- 原模型分类 ACC：{baseline['classification_accuracy']:.4f}
- 新模型分类 ACC：{candidate['classification_accuracy']:.4f}（变化 {delta['classification_accuracy']:+.4f}）
- 原模型缺陷 IoU / Dice / Recall：{baseline['defect_iou']:.4f} / {baseline['defect_dice']:.4f} / {baseline['defect_recall']:.4f}
- 新模型缺陷 IoU / Dice / Recall：{candidate['defect_iou']:.4f} / {candidate['defect_dice']:.4f} / {candidate['defect_recall']:.4f}
- 原模型分类 Loss：{baseline['classification_loss']:.4f}
- 新模型分类 Loss：{candidate['classification_loss']:.4f}

## 学校报告声称值（仅作非同条件参考）

- ACC 0.9655，Recall 0.9375，Loss 0.1263，mIoU 0.8626。
- 学校原始数据划分、训练日志及指标实现未知，因此本结果不能被表述为严格同条件复现。
"""


def compare_multitask_models(
    config_path,
    manifest_path,
    baseline_model_dir,
    candidate_model_dir,
    output_dir,
    bootstrap_samples=1000,
    seed=1,
):
    """Evaluate two artifacts on identical rows and write paired evidence."""
    config = load_config(config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(manifest_path)

    baseline_model = load_saved_model(baseline_model_dir)
    image_size = int(baseline_model.input_shape[1])
    del baseline_model
    tf.keras.backend.clear_session()
    images, labels, masks, rows = load_dataset(
        manifest_path,
        config.path("data"),
        "test",
        image_size=image_size,
        include_masks=True,
        return_rows=True,
    )
    baseline_class, baseline_seg, baseline_size = _predict(
        baseline_model_dir, images
    )
    candidate_class, candidate_seg, candidate_size = _predict(
        candidate_model_dir, images
    )
    if baseline_size != candidate_size:
        raise ValueError("baseline and candidate input sizes differ")

    (
        baseline_flat,
        baseline_class_full,
        baseline_seg_full,
        baseline_class_matrix,
        baseline_seg_matrix,
    ) = _summary(labels, masks, baseline_class, baseline_seg)
    (
        candidate_flat,
        candidate_class_full,
        candidate_seg_full,
        candidate_class_matrix,
        candidate_seg_matrix,
    ) = _summary(labels, masks, candidate_class, candidate_seg)
    delta = {
        name: float(candidate_flat[name] - baseline_flat[name])
        for name in baseline_flat
    }
    intervals = _paired_bootstrap(
        labels,
        masks,
        baseline_class,
        baseline_seg,
        candidate_class,
        candidate_seg,
        samples=bootstrap_samples,
        seed=seed,
    )
    promotion = {
        "defect_iou_improvement_at_least_0.05": delta["defect_iou"] >= 0.05,
        "defect_recall_improvement_at_least_0.05": (
            delta["defect_recall"] >= 0.05
        ),
        "classification_accuracy_drop_at_most_0.03": (
            delta["classification_accuracy"] >= -0.03
        ),
    }
    promotion["passed"] = all(promotion.values())
    result = {
        "samples": len(rows),
        "manifest": str(manifest_path.resolve()),
        "baseline_model_dir": str(Path(baseline_model_dir).resolve()),
        "candidate_model_dir": str(Path(candidate_model_dir).resolve()),
        "baseline": baseline_flat,
        "candidate": candidate_flat,
        "delta": delta,
        "bootstrap_95_ci": intervals,
        "promotion_gate": promotion,
        "school_reported_reference": SCHOOL_REFERENCE,
        "school_comparison_is_strictly_equivalent": False,
        "classification_details": {
            "baseline": baseline_class_full,
            "candidate": candidate_class_full,
        },
        "segmentation_details": {
            "baseline": baseline_seg_full,
            "candidate": candidate_seg_full,
        },
    }
    (output_dir / "comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "COMPARISON_REPORT.md").write_text(
        _report(result), encoding="utf-8"
    )
    for prefix, class_matrix, seg_matrix in (
        ("baseline", baseline_class_matrix, baseline_seg_matrix),
        ("candidate", candidate_class_matrix, candidate_seg_matrix),
    ):
        _save_confusion_matrix(
            class_matrix,
            CLASS_NAMES,
            f"{prefix}_classification_confusion_matrix",
            output_dir,
        )
        _save_confusion_matrix(
            seg_matrix,
            SEGMENT_NAMES,
            f"{prefix}_segmentation_confusion_matrix",
            output_dir,
        )
    _write_predictions(
        rows,
        labels,
        masks,
        baseline_class,
        baseline_seg,
        candidate_class,
        candidate_seg,
        output_dir / "predictions.csv",
    )
    return result
