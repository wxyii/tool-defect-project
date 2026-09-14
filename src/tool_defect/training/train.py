"""Train the retained classification or multitask source model."""

import json
from pathlib import Path

import tensorflow as tf

from tool_defect.config import load_config
from tool_defect.data.datasets import load_dataset
from tool_defect.inference.input_pipeline import (
    inference_mode_from_data_path,
    write_inference_metadata,
)
from tool_defect.models.classifier import build_classifier
from tool_defect.models.multitask import build_multitask
from tool_defect.training.checkpointing import (
    ParentClassificationMetricsCallback,
    parent_labels_for_rows,
)
from tool_defect.training.objectives import DefectDice, DefectIoU


_USE_CONFIG = object()


def _checkpoint_callbacks(
    output_dir,
    task,
    validation_data,
    validation_rows,
    batch_size,
    validation_parent_labels=None,
):
    """Save the classification-priority best weights and the last weights."""
    monitor = "val_parent_unqualified_recall"
    best = tf.keras.callbacks.ModelCheckpoint(
        output_dir / "weights_best_classification.h5",
        monitor=monitor,
        mode="max",
        save_best_only=True,
        save_weights_only=True,
        verbose=0,
    )
    last = tf.keras.callbacks.ModelCheckpoint(
        output_dir / "weights_last.h5",
        save_best_only=False,
        save_weights_only=True,
        verbose=0,
    )
    parent_metrics = ParentClassificationMetricsCallback(
        validation_data,
        validation_rows,
        batch_size=batch_size,
        validation_parent_labels=validation_parent_labels,
    )
    callbacks = [parent_metrics, tf.keras.callbacks.TerminateOnNaN(), best, last]
    if task == "multitask":
        callbacks.append(
            tf.keras.callbacks.ModelCheckpoint(
                output_dir / "weights_best_segmentation.h5",
                monitor="val_seg_out_defect_dice",
                mode="max",
                save_best_only=True,
                save_weights_only=True,
                verbose=0,
            )
        )
    return callbacks, monitor


def _best_epoch(history, monitor):
    values = history.history.get(monitor, [])
    if not values:
        return None, None
    values = [float(value) for value in values]
    index = int(max(range(len(values)), key=values.__getitem__))
    return index + 1, values[index]


def _resolve_backbone_weights(config, value):
    if value is _USE_CONFIG:
        return config
    if isinstance(value, str) and value.lower() in {"none", "null", ""}:
        return None
    return value


def train(
    task,
    config_path,
    epochs=None,
    batch_size=None,
    max_samples=None,
    backbone_weights=_USE_CONFIG,
    output_dir=None,
):
    if task not in {"classification", "multitask"}:
        raise ValueError("task must be 'classification' or 'multitask'")

    config = load_config(config_path)
    section = config.values[task]
    image_size = config.image_size
    epochs = int(epochs if epochs is not None else section["epochs"])
    batch_size = int(
        batch_size if batch_size is not None else section["batch_size"]
    )
    backbone_weights = _resolve_backbone_weights(
        section.get("backbone_weights"), backbone_weights
    )
    data_root = config.path("data")
    manifest = config.path("manifest")
    output_dir = Path(
        output_dir
        if output_dir is not None
        else config.path("outputs") / "training" / task
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    tf.keras.utils.set_random_seed(int(config.get("seed", 1)))
    if task == "classification":
        train_images, train_labels = load_dataset(
            manifest,
            data_root,
            "train",
            image_size=image_size,
            max_samples=max_samples,
            include_masks=False,
        )
        validation_images, validation_labels, validation_rows = load_dataset(
            manifest,
            data_root,
            "validation",
            image_size=image_size,
            max_samples=max_samples,
            include_masks=False,
            return_rows=True,
        )
        validation_parent_labels = parent_labels_for_rows(
            validation_rows,
            data_root / "manifests" / "provenance.csv",
        )
        model = build_classifier(
            input_shape=(image_size, image_size, 3),
            backbone_weights=backbone_weights,
        )
        model.compile(
            optimizer=tf.keras.optimizers.Adam(
                learning_rate=float(section["learning_rate"])
            ),
            loss="categorical_crossentropy",
            metrics=[
                "accuracy",
                tf.keras.metrics.Precision(
                    name="unqualified_precision", class_id=1
                ),
                tf.keras.metrics.Recall(
                    name="unqualified_recall", class_id=1
                ),
            ],
        )
        callbacks, monitor = _checkpoint_callbacks(
            output_dir,
            task,
            validation_images,
            validation_rows,
            batch_size,
            validation_parent_labels,
        )
        history = model.fit(
            train_images,
            train_labels,
            validation_data=(validation_images, validation_labels),
            epochs=epochs,
            batch_size=batch_size,
            callbacks=callbacks,
            verbose=2,
        )
    else:
        train_images, train_labels, train_masks = load_dataset(
            manifest,
            data_root,
            "train",
            image_size=image_size,
            max_samples=max_samples,
            include_masks=True,
        )
        (
            validation_images,
            validation_labels,
            validation_masks,
            validation_rows,
        ) = load_dataset(
            manifest,
            data_root,
            "validation",
            image_size=image_size,
            max_samples=max_samples,
            include_masks=True,
            return_rows=True,
        )
        validation_parent_labels = parent_labels_for_rows(
            validation_rows,
            data_root / "manifests" / "provenance.csv",
        )
        model = build_multitask(
            input_shape=(image_size, image_size, 3),
            backbone_weights=backbone_weights,
        )
        model.compile(
            optimizer=tf.keras.optimizers.Adam(
                learning_rate=float(section["learning_rate"])
            ),
            loss={
                "cla_out": "categorical_crossentropy",
                "seg_out": "categorical_crossentropy",
            },
            metrics={
                "cla_out": [
                    "accuracy",
                    tf.keras.metrics.Precision(
                        name="unqualified_precision", class_id=1
                    ),
                    tf.keras.metrics.Recall(
                        name="unqualified_recall", class_id=1
                    ),
                ],
                "seg_out": [DefectIoU(), DefectDice()],
            },
        )
        callbacks, monitor = _checkpoint_callbacks(
            output_dir,
            task,
            validation_images,
            validation_rows,
            batch_size,
            validation_parent_labels,
        )
        history = model.fit(
            train_images,
            {"cla_out": train_labels, "seg_out": train_masks},
            validation_data=(
                validation_images,
                {
                    "cla_out": validation_labels,
                    "seg_out": validation_masks,
                },
            ),
            epochs=epochs,
            batch_size=batch_size,
            callbacks=callbacks,
            verbose=2,
        )

    (output_dir / "model.json").write_text(model.to_json(), encoding="utf-8")
    write_inference_metadata(
        output_dir,
        inference_mode_from_data_path(data_root),
    )
    model.save_weights(output_dir / "weights_last.h5")
    best_path = output_dir / "weights_best_classification.h5"
    if not best_path.is_file():
        raise RuntimeError(
            f"未生成分类优先最佳权重，验证指标 {monitor!r} 不可用"
        )
    model.load_weights(best_path)
    model.save_weights(output_dir / "weights.h5")
    best_epoch, best_value = _best_epoch(history, monitor)
    (output_dir / "weight_selection.json").write_text(
        json.dumps(
            {
                "primary_metric": monitor,
                "decision_threshold_for_selection": 0.5,
                "parent_id_rule": "parent_sample_id or patch filename before __patch_",
                "best_epoch": best_epoch,
                "best_value": best_value,
                "weights_h5": "weights_best_classification.h5",
                "weights_last_h5": "weights_last.h5",
                "weights_compatibility_alias": "weights.h5",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return history.history
