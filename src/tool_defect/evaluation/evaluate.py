"""Evaluate supplied artifacts and save auditable metrics."""

import csv
import json
from pathlib import Path
import warnings

import numpy as np

from tool_defect.config import load_config
from tool_defect.data.datasets import load_dataset
from tool_defect.data.preprocess import (
    apply_input_preprocessing,
    artifact_preprocessing_mode,
)
from tool_defect.evaluation.metrics import (
    CLASS_NAMES,
    SEGMENT_NAMES,
    classification_metrics,
    segmentation_metrics,
)
from tool_defect.models.loader import load_saved_model


def _save_confusion_matrix(matrix, labels, stem, output_dir):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=DeprecationWarning)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

    csv_path = output_dir / f"{stem}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["true/predicted", *labels])
        for label, row in zip(labels, matrix):
            writer.writerow([label, *[int(value) for value in row]])

    figure, axis = plt.subplots(figsize=(5, 4))
    image = axis.imshow(matrix, interpolation="nearest", cmap="Blues")
    figure.colorbar(image, ax=axis)
    axis.set(
        xticks=np.arange(len(labels)),
        yticks=np.arange(len(labels)),
        xticklabels=labels,
        yticklabels=labels,
        xlabel="Predicted label",
        ylabel="True label",
    )
    threshold = matrix.max() / 2 if matrix.size else 0
    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            axis.text(
                column,
                row,
                str(int(matrix[row, column])),
                ha="center",
                va="center",
                color="white" if matrix[row, column] > threshold else "black",
            )
    figure.tight_layout()
    figure.savefig(output_dir / f"{stem}.png", dpi=180)
    plt.close(figure)


def _write_predictions(rows, labels, probabilities, destination, segmentation=None):
    fieldnames = [
        "sample_id",
        "image_path",
        "true_label",
        "true_class",
        "predicted_label",
        "predicted_class",
        "qualified_probability",
        "unqualified_probability",
    ]
    if segmentation is not None:
        fieldnames.extend(["defect_iou", "defect_dice"])
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, (row, label, probability) in enumerate(
            zip(rows, labels, probabilities)
        ):
            true_label = int(np.argmax(label))
            predicted_label = int(np.argmax(probability))
            output = {
                "sample_id": row["sample_id"],
                "image_path": row["image_path"],
                "true_label": true_label,
                "true_class": CLASS_NAMES[true_label],
                "predicted_label": predicted_label,
                "predicted_class": CLASS_NAMES[predicted_label],
                "qualified_probability": f"{float(probability[0]):.8f}",
                "unqualified_probability": f"{float(probability[1]):.8f}",
            }
            if segmentation is not None:
                true_mask, predicted_mask = segmentation[index]
                sample_metrics, _ = segmentation_metrics(
                    true_mask[None, ...], predicted_mask[None, ...]
                )
                output["defect_iou"] = f"{sample_metrics['defect']['iou']:.8f}"
                output["defect_dice"] = f"{sample_metrics['defect']['dice']:.8f}"
            writer.writerow(output)


def evaluate(
    task,
    config_path,
    max_samples=None,
    model_dir=None,
    split="validation",
    output_dir=None,
    full_metrics=False,
):
    if task not in {"classification", "multitask"}:
        raise ValueError("task must be 'classification' or 'multitask'")
    if split not in {"train", "validation", "test"}:
        raise ValueError("split must be 'train', 'validation', or 'test'")
    config = load_config(config_path)
    model_key = (
        "classification_model" if task == "classification" else "multitask_model"
    )
    model_dir = Path(model_dir or config.path(model_key))
    model = load_saved_model(model_dir)
    preprocessing = artifact_preprocessing_mode(model_dir)
    image_size = int(model.input_shape[1])

    if task == "classification":
        images, labels, rows = load_dataset(
            config.path("manifest"),
            config.path("data"),
            split,
            image_size=image_size,
            max_samples=max_samples,
            include_masks=False,
            return_rows=True,
        )
        class_probabilities = np.asarray(
            model.predict(
                apply_input_preprocessing(images, preprocessing),
                verbose=0,
            )
        )
        segmentation_probabilities = None
        masks = None
    else:
        images, labels, masks, rows = load_dataset(
            config.path("manifest"),
            config.path("data"),
            split,
            image_size=image_size,
            max_samples=max_samples,
            include_masks=True,
            return_rows=True,
        )
        predictions = model.predict(
            apply_input_preprocessing(images, preprocessing),
            verbose=0,
        )
        named = dict(zip(model.output_names, predictions))
        class_probabilities = np.asarray(named["cla_out"])
        segmentation_probabilities = np.asarray(named["seg_out"])

    classification, classification_matrix = classification_metrics(
        np.argmax(labels, axis=-1),
        class_probabilities,
    )
    result = {
        "task": task,
        "split": split,
        "samples": int(len(images)),
        "classification_accuracy": classification["accuracy"],
        "classification": classification,
    }
    if task == "multitask":
        segmentation, segmentation_matrix = segmentation_metrics(
            masks, segmentation_probabilities
        )
        result["mean_iou"] = segmentation["mean_iou"]
        result["segmentation"] = segmentation
        result["total_standardized_loss"] = (
            classification["cross_entropy_loss"]
            + segmentation["cross_entropy_loss"]
        )

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "metrics.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _save_confusion_matrix(
            classification_matrix,
            CLASS_NAMES,
            "classification_confusion_matrix",
            output_dir,
        )
        if task == "multitask":
            _save_confusion_matrix(
                segmentation_matrix,
                SEGMENT_NAMES,
                "segmentation_confusion_matrix",
                output_dir,
            )
            segmentation_pairs = list(zip(masks, segmentation_probabilities))
        else:
            segmentation_pairs = None
        _write_predictions(
            rows,
            labels,
            class_probabilities,
            output_dir / "predictions.csv",
            segmentation=segmentation_pairs,
        )
    return result
