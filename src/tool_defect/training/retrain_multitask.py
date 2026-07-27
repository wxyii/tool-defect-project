"""Warm-start and archive a two-stage multitask retraining experiment."""

import csv
import hashlib
import json
import platform
import re
import shutil
import sys
from datetime import datetime
from importlib import metadata as package_metadata
from pathlib import Path

import numpy as np
import tensorflow as tf

from tool_defect.config import load_config
from tool_defect.models.loader import load_saved_model
from tool_defect.training.objectives import (
    DefectDice,
    DefectIoU,
    DefectPrecision,
    DefectRecall,
    combined_segmentation_loss,
)
from tool_defect.training.sequence import BalancedMultitaskSequence


_LATE_BACKBONE = re.compile(r"^block(?:11|12|13|14)_")


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_existing_best(history_path):
    history_path = Path(history_path)
    if not history_path.is_file():
        return -np.inf, None
    best = -np.inf
    best_epoch = None
    with history_path.open(newline="", encoding="utf-8") as handle:
        for absolute_epoch, row in enumerate(csv.DictReader(handle), start=1):
            value = row.get("val_joint_score")
            if value in (None, ""):
                continue
            score = float(value)
            if np.isfinite(score) and score > best:
                best = score
                best_epoch = absolute_epoch
    return best, best_epoch


def _completed_epoch_count(history_path):
    history_path = Path(history_path)
    if not history_path.is_file():
        return 0
    with history_path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for row in csv.DictReader(handle) if row.get("loss"))


def configure_trainable_layers(model, stage):
    """Apply the approved freeze policy without changing the model topology."""
    if stage == 1:
        return model
    if stage != 2:
        raise ValueError("stage must be 1 or 2")
    convolution_types = (
        tf.keras.layers.Conv2D,
        tf.keras.layers.SeparableConv2D,
        tf.keras.layers.DepthwiseConv2D,
    )
    for layer in model.layers:
        if not _LATE_BACKBONE.match(layer.name):
            continue
        if isinstance(layer, tf.keras.layers.BatchNormalization):
            layer.trainable = False
        elif isinstance(layer, convolution_types):
            layer.trainable = True
    return model


def _compile(model, learning_rate):
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=float(learning_rate)),
        loss={
            "cla_out": tf.keras.losses.CategoricalCrossentropy(
                label_smoothing=0.05
            ),
            "seg_out": combined_segmentation_loss,
        },
        loss_weights={"cla_out": 1.0, "seg_out": 1.0},
        metrics={
            "cla_out": [
                tf.keras.metrics.CategoricalAccuracy(name="accuracy"),
                tf.keras.metrics.Precision(
                    name="unqualified_precision", class_id=1
                ),
                tf.keras.metrics.Recall(name="unqualified_recall", class_id=1),
            ],
            "seg_out": [
                DefectIoU(),
                DefectDice(),
                DefectPrecision(),
                DefectRecall(),
            ],
        },
    )


class _JointBestCheckpoint(tf.keras.callbacks.Callback):
    def __init__(self, destination, patience):
        super().__init__()
        self.destination = Path(destination)
        self.patience = int(patience)
        self.best = -np.inf
        self.best_epoch = None
        self.global_epoch_offset = 0
        self.wait = 0

    def start_stage(self, patience, global_epoch_offset):
        self.patience = int(patience)
        self.global_epoch_offset = int(global_epoch_offset)
        self.wait = 0

    def on_epoch_end(self, epoch, logs=None):
        logs = logs or {}
        accuracy = logs.get("val_cla_out_accuracy")
        dice = logs.get("val_seg_out_defect_dice")
        if accuracy is None or dice is None:
            raise RuntimeError(
                "validation joint score metrics are missing from training logs"
            )
        score = 0.4 * float(accuracy) + 0.6 * float(dice)
        logs["val_joint_score"] = score
        absolute_epoch = self.global_epoch_offset + int(epoch) + 1
        if np.isfinite(score) and score > self.best + 1e-8:
            self.best = score
            self.best_epoch = absolute_epoch
            self.wait = 0
            self.model.save_weights(self.destination)
        else:
            self.wait += 1
            if self.wait >= self.patience:
                self.model.stop_training = True


def _callbacks(run_dir, stage, settings, joint_callback):
    reduce_settings = settings["reduce_lr"]
    stage_settings = settings[f"stage{stage}"]
    return [
        joint_callback,
        tf.keras.callbacks.TerminateOnNaN(),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=float(reduce_settings["factor"]),
            patience=int(reduce_settings["patience"]),
            min_lr=float(reduce_settings["min_lr"]),
            verbose=1,
        ),
        tf.keras.callbacks.ModelCheckpoint(
            run_dir / "weights_last.h5",
            save_weights_only=True,
            save_best_only=False,
            verbose=0,
        ),
        tf.keras.callbacks.ModelCheckpoint(
            run_dir / f"stage{stage}_last.h5",
            save_weights_only=True,
            save_best_only=False,
            verbose=0,
        ),
        tf.keras.callbacks.CSVLogger(
            run_dir / "history.csv",
            append=stage == 2 or (run_dir / "history.csv").exists(),
        ),
    ]


def _environment_text():
    packages = (
        "tensorflow",
        "keras",
        "numpy",
        "scikit-learn",
        "opencv-python",
        "Pillow",
    )
    lines = [
        f"python={sys.version.replace(chr(10), ' ')}",
        f"platform={platform.platform()}",
        f"tensorflow={tf.__version__}",
        f"physical_gpus={len(tf.config.list_physical_devices('GPU'))}",
    ]
    for package in packages:
        try:
            version = package_metadata.version(package)
        except package_metadata.PackageNotFoundError:
            version = "not-installed"
        lines.append(f"{package}={version}")
    return "\n".join(lines) + "\n"


def _json_history(history_by_stage):
    return {
        stage: {
            name: [float(value) for value in values]
            for name, values in history.items()
        }
        for stage, history in history_by_stage.items()
    }


def retrain_multitask(
    config_path,
    init_model_dir=None,
    output_root=None,
    run_id=None,
    smoke=False,
    resume=None,
):
    """Run the approved two-stage warm-start experiment and return its directory."""
    config = load_config(config_path)
    settings = config.values["retrain_multitask"]
    init_model_dir = Path(
        init_model_dir or config.path("multitask_model")
    ).resolve()
    output_root = Path(
        output_root or config.path("retrained_output")
    ).resolve()
    if resume is not None:
        resume_path = Path(resume).resolve()
        run_dir = resume_path if resume_path.is_dir() else resume_path.parent
        resume_weights = (
            run_dir / "weights_last.h5"
            if resume_path.is_dir()
            else resume_path
        )
        if not resume_weights.is_file():
            raise FileNotFoundError(f"resume weights not found: {resume_weights}")
    else:
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = output_root / run_id
        if run_dir.exists():
            raise FileExistsError(f"run directory already exists: {run_dir}")
        run_dir.mkdir(parents=True)
        resume_weights = None

    source_files = {
        name: init_model_dir / name for name in ("model.json", "weights.h5")
    }
    source_hashes = {name: _sha256(path) for name, path in source_files.items()}
    model = load_saved_model(init_model_dir)
    if model.output_names != ["cla_out", "seg_out"]:
        raise ValueError(
            f"unexpected multitask outputs: {model.output_names}; expected cla_out, seg_out"
        )
    if resume_weights is not None:
        model.load_weights(resume_weights)

    image_size = int(model.input_shape[1])
    configured_size = int(config.image_size)
    if image_size != configured_size:
        raise ValueError(
            f"artifact input size {image_size} does not match config {configured_size}"
        )
    seed = int(config.get("seed", 1))
    tf.keras.utils.set_random_seed(seed)
    manifest = config.path("manifest")
    data_root = config.path("data")
    batch_size = int(settings["batch_size"])
    training = BalancedMultitaskSequence(
        manifest,
        data_root,
        "train",
        image_size=image_size,
        batch_size=batch_size,
        seed=seed,
        augment=True,
        photometric=True,
        balanced=True,
    )
    validation = BalancedMultitaskSequence(
        manifest,
        data_root,
        "validation",
        image_size=image_size,
        batch_size=batch_size,
        seed=seed,
        augment=False,
        photometric=False,
        balanced=False,
    )

    (run_dir / "model.json").write_text(model.to_json(), encoding="utf-8")
    if not (run_dir / "weights.h5").exists():
        model.save_weights(run_dir / "weights.h5")
    (run_dir / "config.json").write_text(
        json.dumps(config.values, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shutil.copy2(manifest, run_dir / "manifest.csv")
    (run_dir / "environment.txt").write_text(
        _environment_text(), encoding="utf-8"
    )
    metadata = {
        "status": "running",
        "run_id": run_dir.name,
        "started_at": datetime.now().astimezone().isoformat(),
        "smoke": bool(smoke),
        "resume_from": str(resume_weights) if resume_weights else None,
        "initial_model_dir": str(init_model_dir),
        "initial_artifact_sha256": source_hashes,
        "output_names": list(model.output_names),
        "input_shape": list(model.input_shape),
        "joint_score": "0.4*val_cla_out_accuracy + 0.6*val_seg_out_defect_dice",
    }
    metadata_path = run_dir / "run_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    histories = {}
    prior_best, prior_best_epoch = _read_existing_best(
        run_dir / "history.csv"
    )
    global_epoch_offset = _completed_epoch_count(run_dir / "history.csv")
    joint = _JointBestCheckpoint(
        run_dir / "weights.h5",
        patience=int(settings["stage1"]["patience"]),
    )
    joint.best = prior_best
    joint.best_epoch = prior_best_epoch
    try:
        for stage in (1, 2):
            if stage == 2:
                model.load_weights(run_dir / "weights.h5")
            configure_trainable_layers(model, stage)
            stage_settings = settings[f"stage{stage}"]
            _compile(model, stage_settings["learning_rate"])
            epochs = 1 if smoke else int(stage_settings["epochs"])
            joint.start_stage(
                patience=int(stage_settings["patience"]),
                global_epoch_offset=global_epoch_offset,
            )
            fit_kwargs = {
                "validation_data": validation,
                "epochs": epochs,
                "verbose": 2,
                "callbacks": _callbacks(run_dir, stage, settings, joint),
                "workers": 1,
                "use_multiprocessing": False,
                "max_queue_size": 1,
            }
            if smoke:
                fit_kwargs["steps_per_epoch"] = 1
                fit_kwargs["validation_steps"] = 1
            history = model.fit(training, **fit_kwargs)
            histories[f"stage{stage}"] = history.history
            completed_epochs = len(history.history.get("loss", []))
            global_epoch_offset += completed_epochs
            model.save_weights(run_dir / f"stage{stage}_last.h5")
            model.save_weights(run_dir / "weights_last.h5")

        model.load_weights(run_dir / "weights.h5")
        (run_dir / "model.json").write_text(model.to_json(), encoding="utf-8")
        (run_dir / "history.json").write_text(
            json.dumps(_json_history(histories), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        metadata.update(
            {
                "status": "completed",
                "finished_at": datetime.now().astimezone().isoformat(),
                "epochs_completed": global_epoch_offset,
                "best_joint_score": (
                    float(joint.best) if np.isfinite(joint.best) else None
                ),
                "best_epoch": joint.best_epoch,
                "final_source_artifact_sha256": {
                    name: _sha256(path) for name, path in source_files.items()
                },
            }
        )
    except Exception as error:
        metadata.update(
            {
                "status": "failed",
                "finished_at": datetime.now().astimezone().isoformat(),
                "error": f"{type(error).__name__}: {error}",
            }
        )
        raise
    finally:
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return run_dir
