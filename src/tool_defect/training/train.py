"""Train the retained classification or multitask source model."""

from pathlib import Path

import tensorflow as tf

from tool_defect.config import load_config
from tool_defect.data.datasets import load_dataset
from tool_defect.models.classifier import build_classifier
from tool_defect.models.multitask import build_multitask


_USE_CONFIG = object()


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
        validation_images, validation_labels = load_dataset(
            manifest,
            data_root,
            "validation",
            image_size=image_size,
            max_samples=max_samples,
            include_masks=False,
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
            metrics=["accuracy", tf.keras.metrics.Recall(name="recall")],
        )
        history = model.fit(
            train_images,
            train_labels,
            validation_data=(validation_images, validation_labels),
            epochs=epochs,
            batch_size=batch_size,
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
        validation_images, validation_labels, validation_masks = load_dataset(
            manifest,
            data_root,
            "validation",
            image_size=image_size,
            max_samples=max_samples,
            include_masks=True,
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
                "cla_out": ["accuracy"],
                "seg_out": [tf.keras.metrics.CategoricalAccuracy(name="accuracy")],
            },
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
            verbose=2,
        )

    (output_dir / "model.json").write_text(model.to_json(), encoding="utf-8")
    model.save_weights(output_dir / "weights.h5")
    return history.history
