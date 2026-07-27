import sys
import unittest
from pathlib import Path

import numpy as np
import tensorflow as tf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tool_defect.training.objectives import (
    DefectDice,
    DefectIoU,
    DefectPrecision,
    DefectRecall,
    combined_segmentation_loss,
)


def _one_hot(ids):
    return tf.one_hot(np.asarray(ids, dtype=np.int32), depth=2)


class TrainingObjectiveTests(unittest.TestCase):
    def test_perfect_defect_prediction_has_low_loss_and_unit_metrics(self):
        targets = _one_hot([[[0, 1], [0, 1]]])
        probabilities = tf.cast(targets, tf.float32) * 0.9998 + 0.0001

        loss = float(combined_segmentation_loss(targets, probabilities).numpy())
        self.assertLess(loss, 0.001)
        for metric_class in (
            DefectIoU,
            DefectDice,
            DefectPrecision,
            DefectRecall,
        ):
            metric = metric_class()
            metric.update_state(targets, probabilities)
            self.assertAlmostEqual(1.0, float(metric.result().numpy()), places=6)

    def test_missing_a_defect_increases_loss_and_reduces_recall(self):
        targets = _one_hot([[[0, 1], [0, 1]]])
        missed = _one_hot([[[0, 0], [0, 1]]])
        perfect = tf.cast(targets, tf.float32) * 0.9998 + 0.0001
        missed = tf.cast(missed, tf.float32) * 0.9998 + 0.0001

        self.assertGreater(
            float(combined_segmentation_loss(targets, missed).numpy()),
            float(combined_segmentation_loss(targets, perfect).numpy()),
        )
        recall = DefectRecall()
        recall.update_state(targets, missed)
        self.assertAlmostEqual(0.5, float(recall.result().numpy()), places=6)

    def test_empty_qualified_mask_has_finite_loss_and_metrics(self):
        targets = _one_hot([[[0, 0], [0, 0]]])
        probabilities = tf.constant(
            [[[[0.99, 0.01], [0.99, 0.01]], [[0.99, 0.01], [0.99, 0.01]]]],
            dtype=tf.float32,
        )

        self.assertTrue(
            np.isfinite(float(combined_segmentation_loss(targets, probabilities)))
        )
        for metric_class in (
            DefectIoU,
            DefectDice,
            DefectPrecision,
            DefectRecall,
        ):
            metric = metric_class()
            metric.update_state(targets, probabilities)
            self.assertTrue(np.isfinite(float(metric.result().numpy())))


if __name__ == "__main__":
    unittest.main()
