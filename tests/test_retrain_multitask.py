import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import tensorflow as tf
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tool_defect.cli import build_parser
from tool_defect.training.retrain_multitask import (
    _read_existing_best,
    configure_trainable_layers,
    retrain_multitask,
)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tiny_model():
    inputs = tf.keras.Input((8, 8, 3), name="image")
    early = tf.keras.layers.Conv2D(
        4, 1, name="block10_conv1", trainable=False
    )(inputs)
    block = tf.keras.layers.Conv2D(
        4, 1, name="block11_conv1", trainable=False
    )(early)
    block = tf.keras.layers.BatchNormalization(
        name="block11_bn", trainable=True
    )(block)
    pooled = tf.keras.layers.GlobalAveragePooling2D()(block)
    classification = tf.keras.layers.Dense(
        2, activation="softmax", name="cla_out"
    )(pooled)
    segmentation = tf.keras.layers.Conv2D(
        2, 1, activation="softmax", name="seg_out"
    )(block)
    return tf.keras.Model(inputs, [classification, segmentation])


def _write_fixture(root):
    data_root = root / "data"
    rows = []
    for split in ("train", "validation"):
        for label_name, label in (("qualified", 0), ("unqualified", 1)):
            image_rel = (
                Path("images") / label_name / f"{split}_{label_name}.png"
            )
            mask_rel = Path("masks") / label_name / f"{split}_{label_name}.png"
            image_path = data_root / image_rel
            mask_path = data_root / mask_rel
            image_path.parent.mkdir(parents=True, exist_ok=True)
            mask_path.parent.mkdir(parents=True, exist_ok=True)
            mask = np.zeros((8, 8), dtype=np.uint8)
            if label:
                mask[2:5, 3:6] = 255
            Image.fromarray(np.repeat(mask[..., None], 3, axis=-1)).save(
                image_path
            )
            Image.fromarray(mask).save(mask_path)
            rows.append(
                {
                    "sample_id": f"{label_name}/{split}.png",
                    "image_path": image_rel.as_posix(),
                    "mask_path": mask_rel.as_posix(),
                    "annotation_path": "",
                    "label": str(label),
                    "label_name": label_name,
                    "split": split,
                }
            )
    manifest = data_root / "manifests" / "curated_v1_retrain.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    model_dir = root / "artifacts" / "multitask"
    model_dir.mkdir(parents=True)
    model = _tiny_model()
    (model_dir / "model.json").write_text(model.to_json(), encoding="utf-8")
    model.save_weights(model_dir / "weights.h5")

    config_dir = root / "configs"
    config_dir.mkdir()
    config = {
        "image_size": 8,
        "seed": 1,
        "paths": {
            "data": "data",
            "manifest": "data/manifests/curated_v1_retrain.csv",
            "multitask_model": "artifacts/multitask",
            "outputs": "outputs",
        },
        "retrain_multitask": {
            "batch_size": 2,
            "stage1": {"epochs": 1, "learning_rate": 0.0001, "patience": 1},
            "stage2": {"epochs": 1, "learning_rate": 0.00001, "patience": 1},
            "reduce_lr": {
                "factor": 0.5,
                "patience": 1,
                "min_lr": 0.0000001,
            },
        },
    }
    config_path = config_dir / "retrain_multitask.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path, model_dir


class RetrainMultitaskTests(unittest.TestCase):
    def test_resume_restores_prior_best_joint_score_from_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history = Path(temp_dir) / "history.csv"
            history.write_text(
                "epoch,val_joint_score\n0,0.4251\n1,0.3938\n2,0.3799\n",
                encoding="utf-8",
            )

            best, best_epoch = _read_existing_best(history)

        self.assertAlmostEqual(0.4251, best)
        self.assertEqual(1, best_epoch)

    def test_stage_configuration_preserves_then_selectively_unfreezes(self):
        model = _tiny_model()
        initial = {layer.name: layer.trainable for layer in model.layers}
        configure_trainable_layers(model, stage=1)
        self.assertEqual(
            initial, {layer.name: layer.trainable for layer in model.layers}
        )

        configure_trainable_layers(model, stage=2)
        self.assertFalse(model.get_layer("block10_conv1").trainable)
        self.assertTrue(model.get_layer("block11_conv1").trainable)
        self.assertFalse(model.get_layer("block11_bn").trainable)
        self.assertTrue(model.get_layer("cla_out").trainable)
        self.assertTrue(model.get_layer("seg_out").trainable)

    def test_smoke_retraining_archives_complete_run_without_overwriting_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path, model_dir = _write_fixture(root)
            source_hashes = {
                name: _sha256(model_dir / name)
                for name in ("model.json", "weights.h5")
            }
            run_dir = retrain_multitask(
                config_path=config_path,
                init_model_dir=model_dir,
                output_root=root / "artifacts/multitask_retrained",
                run_id="smoke",
                smoke=True,
            )

            required = (
                "model.json",
                "weights.h5",
                "weights_last.h5",
                "stage1_last.h5",
                "stage2_last.h5",
                "history.csv",
                "history.json",
                "config.json",
                "manifest.csv",
                "environment.txt",
                "run_metadata.json",
            )
            for name in required:
                self.assertTrue((run_dir / name).is_file(), name)
            self.assertEqual(
                source_hashes,
                {
                    name: _sha256(model_dir / name)
                    for name in ("model.json", "weights.h5")
                },
            )
            metadata = json.loads(
                (run_dir / "run_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual("completed", metadata["status"])
            self.assertEqual(["cla_out", "seg_out"], metadata["output_names"])

    def test_cli_exposes_dedicated_multitask_retraining_command(self):
        args = build_parser().parse_args(
            [
                "retrain-multitask",
                "--config",
                "configs/retrain_multitask.json",
                "--run-id",
                "trial",
                "--smoke",
            ]
        )
        self.assertEqual("retrain-multitask", args.command)
        self.assertEqual("trial", args.run_id)
        self.assertTrue(args.smoke)


if __name__ == "__main__":
    unittest.main()
