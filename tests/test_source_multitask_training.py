import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import tensorflow as tf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tool_defect.cli import build_parser
from tool_defect.data.preprocess import (
    XCEPTION,
    apply_input_preprocessing,
    artifact_preprocessing_mode,
)
from tool_defect.training.train_multitask_source import (
    configure_source_trainable_layers,
)


def _tiny_model():
    inputs = tf.keras.Input((8, 8, 3), name="image")
    early = tf.keras.layers.Conv2D(4, 1, name="block10_conv1")(inputs)
    late = tf.keras.layers.Conv2D(4, 1, name="block11_conv1")(early)
    late = tf.keras.layers.BatchNormalization(name="block11_bn")(late)
    classification = tf.keras.layers.GlobalAveragePooling2D()(late)
    classification = tf.keras.layers.Dense(
        2, activation="softmax", name="cla_out"
    )(classification)
    segmentation = tf.keras.layers.Conv2D(
        2, 1, activation="softmax", name="seg_out"
    )(late)
    return tf.keras.Model(inputs, [classification, segmentation])


class SourceMultitaskTrainingTests(unittest.TestCase):
    def test_artifact_preprocessing_is_legacy_safe_and_xception_aware(self):
        images = np.asarray([[[[0.0, 0.5, 1.0]]]], dtype=np.float32)
        with tempfile.TemporaryDirectory() as temp_dir:
            model_dir = Path(temp_dir)
            self.assertEqual("zero_one", artifact_preprocessing_mode(model_dir))
            (model_dir / "preprocessing.json").write_text(
                json.dumps({"mode": XCEPTION}), encoding="utf-8"
            )
            self.assertEqual(XCEPTION, artifact_preprocessing_mode(model_dir))
            converted = apply_input_preprocessing(images, XCEPTION)
            np.testing.assert_allclose(
                converted, [[[[-1.0, 0.0, 1.0]]]], atol=1e-7
            )

    def test_source_freeze_policy_freezes_all_then_only_late_convolutions(self):
        model = _tiny_model()
        configure_source_trainable_layers(model, stage=1)
        self.assertFalse(model.get_layer("block10_conv1").trainable)
        self.assertFalse(model.get_layer("block11_conv1").trainable)
        self.assertFalse(model.get_layer("block11_bn").trainable)
        self.assertTrue(model.get_layer("cla_out").trainable)

        configure_source_trainable_layers(model, stage=2)
        self.assertFalse(model.get_layer("block10_conv1").trainable)
        self.assertTrue(model.get_layer("block11_conv1").trainable)
        self.assertFalse(model.get_layer("block11_bn").trainable)

    def test_cli_exposes_source_training_and_suite_comparison(self):
        train_args = build_parser().parse_args(
            [
                "train-multitask-source",
                "--run-id",
                "source_trial",
                "--smoke",
            ]
        )
        self.assertEqual("train-multitask-source", train_args.command)
        self.assertEqual("source_trial", train_args.run_id)
        self.assertTrue(train_args.smoke)

        suite_args = build_parser().parse_args(
            [
                "compare-multitask-suite",
                "--previous",
                "previous",
                "--candidate",
                "candidate",
                "--output",
                "comparison",
            ]
        )
        self.assertEqual("compare-multitask-suite", suite_args.command)


if __name__ == "__main__":
    unittest.main()
