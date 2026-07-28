"""Three-way comparison for the original, warm-started, and source-trained models."""

import json
from pathlib import Path

import numpy as np
import tensorflow as tf

from tool_defect.config import load_config
from tool_defect.data.datasets import load_dataset
from tool_defect.evaluation.compare_multitask import (
    _predict,
    compare_multitask_models,
)
from tool_defect.evaluation.metrics import (
    classification_metrics,
    segmentation_metrics,
)
from tool_defect.models.loader import load_saved_model


def _image_size(model_dir):
    model = load_saved_model(model_dir)
    size = int(model.input_shape[1])
    del model
    tf.keras.backend.clear_session()
    return size


def _best_validation_threshold(masks, probabilities):
    candidates = np.round(np.arange(0.10, 0.901, 0.05), 2)
    scored = []
    for threshold in candidates:
        metrics, _ = segmentation_metrics(
            masks, probabilities, threshold=threshold
        )
        scored.append(
            (
                metrics["defect"]["dice"],
                metrics["defect"]["iou"],
                -abs(float(threshold) - 0.5),
                float(threshold),
            )
        )
    return max(scored)[-1]


def _metrics_at_threshold(labels, masks, classification, segmentation, threshold):
    classification_result, _ = classification_metrics(
        np.argmax(labels, axis=-1), classification
    )
    segmentation_result, _ = segmentation_metrics(
        masks, segmentation, threshold=threshold
    )
    return {
        "threshold": float(threshold),
        "classification_accuracy": classification_result["accuracy"],
        "classification_loss": classification_result["cross_entropy_loss"],
        "unqualified_precision": classification_result["unqualified"][
            "precision"
        ],
        "unqualified_recall": classification_result["unqualified"]["recall"],
        "unqualified_f1": classification_result["unqualified"]["f1"],
        "defect_iou": segmentation_result["defect"]["iou"],
        "defect_dice": segmentation_result["defect"]["dice"],
        "defect_precision": segmentation_result["defect"]["precision"],
        "defect_recall": segmentation_result["defect"]["recall"],
        "mean_iou": segmentation_result["mean_iou"],
    }


def _report(result):
    baseline = result["models"]["baseline"]["fixed_threshold"]
    previous = result["models"]["previous"]["fixed_threshold"]
    source = result["models"]["source"]["fixed_threshold"]
    gate = "通过" if result["source_promotion_gate"]["passed"] else "未通过"
    return f"""# 三组分类—分割模型测试集对比

- 测试样本：{result['samples']}
- 新源码模型综合门槛：{gate}
- 所有主结果统一使用分割阈值 0.50

| 模型 | 分类ACC | 分类Loss | 缺陷IoU | 缺陷Dice | 缺陷Precision | 缺陷Recall |
|---|---:|---:|---:|---:|---:|---:|
| 原始权重 | {baseline['classification_accuracy']:.4f} | {baseline['classification_loss']:.4f} | {baseline['defect_iou']:.4f} | {baseline['defect_dice']:.4f} | {baseline['defect_precision']:.4f} | {baseline['defect_recall']:.4f} |
| 上一轮重训 | {previous['classification_accuracy']:.4f} | {previous['classification_loss']:.4f} | {previous['defect_iou']:.4f} | {previous['defect_dice']:.4f} | {previous['defect_precision']:.4f} | {previous['defect_recall']:.4f} |
| multitask.py全新训练 | {source['classification_accuracy']:.4f} | {source['classification_loss']:.4f} | {source['defect_iou']:.4f} | {source['defect_dice']:.4f} | {source['defect_precision']:.4f} | {source['defect_recall']:.4f} |

`threshold_tuned` 结果中的阈值只由验证集选择，测试集没有参与调参。
"""


def compare_multitask_suite(
    config_path,
    manifest_path,
    baseline_model_dir,
    previous_model_dir,
    source_model_dir,
    output_dir,
    bootstrap_samples=1000,
    seed=1,
):
    """Write fixed-threshold pairwise evidence plus validation-tuned results."""
    config = load_config(config_path)
    manifest_path = Path(manifest_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_dirs = {
        "baseline": Path(baseline_model_dir),
        "previous": Path(previous_model_dir),
        "source": Path(source_model_dir),
    }
    sizes = {name: _image_size(path) for name, path in model_dirs.items()}
    if len(set(sizes.values())) != 1:
        raise ValueError(f"model input sizes differ: {sizes}")
    image_size = next(iter(sizes.values()))

    previous_pair = compare_multitask_models(
        config_path,
        manifest_path,
        model_dirs["baseline"],
        model_dirs["previous"],
        output_dir / "baseline_vs_previous",
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )
    source_pair = compare_multitask_models(
        config_path,
        manifest_path,
        model_dirs["baseline"],
        model_dirs["source"],
        output_dir / "baseline_vs_source",
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )

    validation_images, validation_labels, validation_masks = load_dataset(
        manifest_path,
        config.path("data"),
        "validation",
        image_size=image_size,
        include_masks=True,
    )
    test_images, test_labels, test_masks = load_dataset(
        manifest_path,
        config.path("data"),
        "test",
        image_size=image_size,
        include_masks=True,
    )
    models = {}
    for name, model_dir in model_dirs.items():
        _, validation_segmentation, _ = _predict(
            model_dir, validation_images
        )
        threshold = _best_validation_threshold(
            validation_masks, validation_segmentation
        )
        test_classification, test_segmentation, _ = _predict(
            model_dir, test_images
        )
        if name == "baseline":
            fixed = source_pair["baseline"]
        elif name == "previous":
            fixed = previous_pair["candidate"]
        else:
            fixed = source_pair["candidate"]
        models[name] = {
            "model_dir": str(model_dir.resolve()),
            "fixed_threshold": fixed,
            "threshold_tuned": _metrics_at_threshold(
                test_labels,
                test_masks,
                test_classification,
                test_segmentation,
                threshold,
            ),
        }

    baseline = models["baseline"]["fixed_threshold"]
    source = models["source"]["fixed_threshold"]
    gate = {
        "defect_iou_higher_than_baseline": (
            source["defect_iou"] > baseline["defect_iou"]
        ),
        "defect_dice_higher_than_baseline": (
            source["defect_dice"] > baseline["defect_dice"]
        ),
        "classification_accuracy_drop_at_most_0.03": (
            source["classification_accuracy"]
            >= baseline["classification_accuracy"] - 0.03
        ),
        "defect_precision_at_least_0.45": (
            source["defect_precision"] >= 0.45
        ),
        "defect_recall_at_least_0.45": source["defect_recall"] >= 0.45,
    }
    gate["passed"] = all(gate.values())
    result = {
        "samples": int(len(test_images)),
        "manifest": str(manifest_path.resolve()),
        "fixed_threshold": 0.5,
        "models": models,
        "source_promotion_gate": gate,
        "test_set_used_for_threshold_selection": False,
    }
    (output_dir / "suite.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "SUITE_REPORT.md").write_text(
        _report(result), encoding="utf-8"
    )
    return result
