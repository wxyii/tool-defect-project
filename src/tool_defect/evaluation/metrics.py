"""Deterministic classification and segmentation metrics."""

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)


CLASS_NAMES = ("qualified", "unqualified")
SEGMENT_NAMES = ("background", "defect")


def _cross_entropy(one_hot_targets, probabilities):
    clipped = np.clip(np.asarray(probabilities, dtype=np.float64), 1e-7, 1.0)
    targets = np.asarray(one_hot_targets, dtype=np.float64)
    return float(-np.mean(np.sum(targets * np.log(clipped), axis=-1)))


def classification_metrics(true_labels, probabilities):
    true_labels = np.asarray(true_labels, dtype=np.int32)
    probabilities = np.asarray(probabilities, dtype=np.float64)
    predicted_labels = np.argmax(probabilities, axis=-1)
    matrix = confusion_matrix(true_labels, predicted_labels, labels=[0, 1])
    precision, recall, f1, support = precision_recall_fscore_support(
        true_labels,
        predicted_labels,
        labels=[0, 1],
        zero_division=0,
    )
    macro = precision_recall_fscore_support(
        true_labels, predicted_labels, average="macro", zero_division=0
    )
    weighted = precision_recall_fscore_support(
        true_labels, predicted_labels, average="weighted", zero_division=0
    )
    result = {
        "accuracy": float(accuracy_score(true_labels, predicted_labels)),
        "cross_entropy_loss": _cross_entropy(
            np.eye(2, dtype=np.float64)[true_labels], probabilities
        ),
        "macro_precision": float(macro[0]),
        "macro_recall": float(macro[1]),
        "macro_f1": float(macro[2]),
        "weighted_precision": float(weighted[0]),
        "weighted_recall": float(weighted[1]),
        "weighted_f1": float(weighted[2]),
    }
    for index, name in enumerate(CLASS_NAMES):
        result[name] = {
            "precision": float(precision[index]),
            "recall": float(recall[index]),
            "f1": float(f1[index]),
            "support": int(support[index]),
        }
    return result, matrix


def _safe_divide(numerator, denominator):
    return float(numerator / denominator) if denominator else 0.0


def segmentation_metrics(true_masks, probabilities, threshold=0.5):
    true_masks = np.asarray(true_masks)
    probabilities = np.asarray(probabilities, dtype=np.float64)
    true_ids = np.argmax(true_masks, axis=-1).reshape(-1)
    predicted_ids = (
        probabilities[..., 1] >= float(threshold)
    ).astype(np.int32).reshape(-1)
    matrix = np.bincount(
        2 * true_ids.astype(np.int64) + predicted_ids.astype(np.int64),
        minlength=4,
    ).reshape(2, 2)

    result = {
        "pixel_accuracy": _safe_divide(np.trace(matrix), matrix.sum()),
        "cross_entropy_loss": _cross_entropy(true_masks, probabilities),
    }
    ious = []
    dices = []
    for index, name in enumerate(SEGMENT_NAMES):
        true_positive = int(matrix[index, index])
        false_negative = int(matrix[index, :].sum() - true_positive)
        false_positive = int(matrix[:, index].sum() - true_positive)
        iou = _safe_divide(
            true_positive,
            true_positive + false_positive + false_negative,
        )
        dice = _safe_divide(
            2 * true_positive,
            2 * true_positive + false_positive + false_negative,
        )
        result[name] = {
            "precision": _safe_divide(
                true_positive, true_positive + false_positive
            ),
            "recall": _safe_divide(
                true_positive, true_positive + false_negative
            ),
            "iou": iou,
            "dice": dice,
            "support_pixels": int(matrix[index, :].sum()),
        }
        ious.append(iou)
        dices.append(dice)
    result["mean_iou"] = float(np.mean(ious))
    result["mean_dice"] = float(np.mean(dices))
    return result, matrix
