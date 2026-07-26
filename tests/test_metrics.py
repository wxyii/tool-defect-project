import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.evaluation.metrics import (
    classification_metrics,
    segmentation_metrics,
)


class MetricTests(unittest.TestCase):
    def test_classification_metrics_report_loss_recall_and_confusion_matrix(self):
        """Catches swapped labels or a loss computed from hard predictions."""
        true_labels = np.asarray([0, 0, 1, 1])
        probabilities = np.asarray(
            [
                [0.9, 0.1],
                [0.4, 0.6],
                [0.7, 0.3],
                [0.2, 0.8],
            ],
            dtype=np.float64,
        )

        metrics, matrix = classification_metrics(true_labels, probabilities)

        np.testing.assert_array_equal(matrix, [[1, 1], [1, 1]])
        self.assertEqual(0.5, metrics["accuracy"])
        self.assertEqual(0.5, metrics["qualified"]["recall"])
        self.assertEqual(0.5, metrics["unqualified"]["recall"])
        expected_loss = -sum(
            math.log(value) for value in (0.9, 0.4, 0.3, 0.8)
        ) / 4
        self.assertAlmostEqual(expected_loss, metrics["cross_entropy_loss"])

    def test_segmentation_metrics_report_defect_iou_dice_and_pixel_matrix(self):
        """Catches background dominance hiding a missed defect."""
        true_ids = np.asarray([[[0, 0], [1, 1]]])
        predicted_ids = np.asarray([[[0, 1], [0, 1]]])
        true_masks = np.eye(2, dtype=np.float32)[true_ids]
        probabilities = np.asarray(
            [
                [
                    [[0.9, 0.1], [0.4, 0.6]],
                    [[0.7, 0.3], [0.2, 0.8]],
                ]
            ],
            dtype=np.float32,
        )

        metrics, matrix = segmentation_metrics(true_masks, probabilities)

        np.testing.assert_array_equal(matrix, [[1, 1], [1, 1]])
        self.assertEqual(0.5, metrics["pixel_accuracy"])
        self.assertEqual(1 / 3, metrics["defect"]["iou"])
        self.assertEqual(0.5, metrics["defect"]["dice"])
        self.assertIn("cross_entropy_loss", metrics)


if __name__ == "__main__":
    unittest.main()
