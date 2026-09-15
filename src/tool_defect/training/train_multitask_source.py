"""Train the retained multitask.py topology with a fresh ImageNet initialization."""

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
from tool_defect.models.multitask import build_multitask
from tool_defect.training.objectives import (
    DefectDice,
    DefectIoU,
    DefectPrecision,
    DefectRecall,
    balanced_segmentation_loss,
)
from tool_defect.training.sequence import BalancedMultitaskSequence


_BACKBONE_LAYER = re.compile(r"^block(?:[1-9]|1[0-4])_")
_LATE_BACKBONE = re.compile(r"^block(?:11|12|13|14)_")
_PREPROCESSING = {
    "mode": "xception",
    "source_range": [0.0, 1.0],
    "model_range": [-1.0, 1.0],
    "formula": "x * 2.0 - 1.0",
}


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _imagenet_cache_path():
    return (
        Path.home()
        / ".keras"
        / "models"
        / "xception_weights_tf_dim_ordering_tf_kernels_notop.h5"
    )


def initialize_imagenet_backbone(model):
    """Copy all 234 ImageNet Xception weight arrays into the custom backbone."""
    image_size = int(model.input_shape[1])
    source = tf.keras.applications.Xception(
        include_top=False,
        weights="imagenet",
        input_shape=(image_size, image_size, 3),
    )
    target = tf.keras.Model(
        model.input,
        model.get_layer("block14_sepconv2_act").output,
        name="custom_xception_transfer_target",
    )
    source_weights = source.get_weights()
    target_weights = target.get_weights()
    if len(source_weights) != 234 or len(target_weights) != 234:
        raise RuntimeError(
            "unexpected Xception weight count; refusing partial ImageNet transfer"
        )
    mismatches = [
        (index, source_value.shape, target_value.shape)
        for index, (source_value, target_value) in enumerate(
            zip(source_weights, target_weights)
        )
        if source_value.shape != target_value.shape
    ]
    if mismatches:
        raise RuntimeError(
            f"ImageNet Xception weights are incompatible: {mismatches[:3]}"
        )
    target.set_weights(source_weights)
    transferred = sum(int(np.prod(value.shape)) for value in source_weights)
    del source
    del target
    return {
        "source": "tf.keras.applications.Xception(include_top=False, weights='imagenet')",
        "weight_arrays": len(source_weights),
        "parameters": transferred,
        "cache_path": str(_imagenet_cache_path()),
        "cache_sha256": (
            _sha256(_imagenet_cache_path())
            if _imagenet_cache_path().is_file()
            else None
        ),
    }


def configure_source_trainable_layers(model, stage):
    """Freeze the complete backbone first, then unfreeze late convolutions only."""
    convolution_types = (
        tf.keras.layers.Conv2D,
        tf.keras.layers.SeparableConv2D,
        tf.keras.layers.DepthwiseConv2D,
    )
    if stage not in (1, 2):
        raise ValueError("stage must be 1 or 2")
    for layer in model.layers:
        if not _BACKBONE_LAYER.match(layer.name):
            continue
        if isinstance(layer, tf.keras.layers.BatchNormalization):
            layer.trainable = False
        elif stage == 1:
            layer.trainable = False
        elif _LATE_BACKBONE.match(layer.name) and isinstance(
            layer, convolution_types
        ):
            layer.trainable = True
        else:
            layer.trainable = False
    return model


def _compile(model, learning_rate):
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=float(learning_rate)),
        loss={
            "cla_out": tf.keras.losses.CategoricalCrossentropy(
                label_smoothing=0.05
            ),
            "seg_out": balanced_segmentation_loss,
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


class _ComprehensiveBestCheckpoint(tf.keras.callbacks.Callback):
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
        iou = logs.get("val_seg_out_defect_iou")
        if accuracy is None or dice is None or iou is None:
            raise RuntimeError("validation metrics required for joint score are missing")
        score = (
            0.30 * float(accuracy)
            + 0.35 * float(dice)
            + 0.35 * float(iou)
        )
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


def _callbacks(run_dir, stage, settings, checkpoint):
    reduce_settings = settings["reduce_lr"]
    return [
        checkpoint,
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


def _json_history(histories):
    return {
        stage: {
            name: [float(value) for value in values]
            for name, values in history.items()
        }
        for stage, history in histories.items()
    }


def train_multitask_source(
    config_path,
    output_root=None,
    run_id=None,
    smoke=False,
    resume=None,
):
    """Build multitask.py, initialize only its backbone from ImageNet, and train."""
    config = load_config(config_path)
    settings = config.values["train_multitask_source"]
    output_root = Path(
        output_root or config.path("source_trained_output")
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
        run_id = run_id or datetime.now().strftime(
            "multitask_source_%Y%m%d_%H%M"
        )
        run_dir = output_root / run_id
        if run_dir.exists():
            raise FileExistsError(f"run directory already exists: {run_dir}")
        resume_weights = None

    seed = int(config.get("seed", 1))
    tf.keras.utils.set_random_seed(seed)
    model = build_multitask(
        input_shape=(config.image_size, config.image_size, 3),
        backbone_weights=None,
    )
    initialization = initialize_imagenet_backbone(model)
    if resume_weights is not None:
        model.load_weights(resume_weights)
    run_dir.mkdir(parents=True, exist_ok=resume is not None)

    manifest = config.path("manifest")
    data_root = config.path("data")
    training = BalancedMultitaskSequence(
        manifest,
        data_root,
        "train",
        image_size=config.image_size,
        batch_size=int(settings["batch_size"]),
        seed=seed,
        augment=True,
        photometric=True,
        balanced=True,
        preprocessing="xception",
    )
    validation = BalancedMultitaskSequence(
        manifest,
        data_root,
        "validation",
        image_size=config.image_size,
        batch_size=int(settings["batch_size"]),
        seed=seed,
        augment=False,
        photometric=False,
        balanced=False,
        preprocessing="xception",
    )

    source_path = Path(__file__).resolve().parents[1] / "models" / "multitask.py"
    (run_dir / "model.json").write_text(model.to_json(), encoding="utf-8")
    (run_dir / "config.json").write_text(
        json.dumps(config.values, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "preprocessing.json").write_text(
        json.dumps(_PREPROCESSING, ensure_ascii=False, indent=2), encoding="utf-8"
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
        "architecture_builder": "tool_defect.models.multitask.build_multitask",
        "architecture_source": str(source_path),
        "architecture_source_sha256": _sha256(source_path),
        "old_project_weights_loaded": False,
        "initialization": initialization,
        "output_names": list(model.output_names),
        "input_shape": list(model.input_shape),
        "model_parameters": int(model.count_params()),
        "joint_score": (
            "0.30*val_cla_out_accuracy + 0.35*val_seg_out_defect_dice "
            "+ 0.35*val_seg_out_defect_iou"
        ),
    }
    metadata_path = run_dir / "run_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    histories = {}
    prior_best, prior_best_epoch = _read_existing_best(run_dir / "history.csv")
    global_epoch_offset = _completed_epoch_count(run_dir / "history.csv")
    checkpoint = _ComprehensiveBestCheckpoint(
        run_dir / "weights.h5",
        patience=int(settings["stage1"]["patience"]),
    )
    checkpoint.best = prior_best
    checkpoint.best_epoch = prior_best_epoch
    try:
        for stage in (1, 2):
            if stage == 2 and (run_dir / "weights.h5").is_file():
                model.load_weights(run_dir / "weights.h5")
            configure_source_trainable_layers(model, stage)
            stage_settings = settings[f"stage{stage}"]
            _compile(model, stage_settings["learning_rate"])
            checkpoint.start_stage(
                stage_settings["patience"],
                global_epoch_offset,
            )
            epochs = 1 if smoke else int(stage_settings["epochs"])
            fit_kwargs = {
                "validation_data": validation,
                "epochs": epochs,
                "verbose": 2,
                "callbacks": _callbacks(
                    run_dir, stage, settings, checkpoint
                ),
                "workers": 1,
                "use_multiprocessing": False,
                "max_queue_size": 1,
            }
            if smoke:
                fit_kwargs["steps_per_epoch"] = 1
                fit_kwargs["validation_steps"] = 1
            history = model.fit(training, **fit_kwargs)
            histories[f"stage{stage}"] = history.history
            global_epoch_offset += len(history.history.get("loss", []))
            model.save_weights(run_dir / f"stage{stage}_last.h5")
            model.save_weights(run_dir / "weights_last.h5")

        if not (run_dir / "weights.h5").is_file():
            raise RuntimeError("training produced no finite validation checkpoint")
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
                "best_joint_score": float(checkpoint.best),
                "best_epoch": checkpoint.best_epoch,
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
