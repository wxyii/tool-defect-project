from pathlib import Path
import sys
import unittest

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/inference-service/src"))
from inference_service.quality.checker import VersionedImageQualityChecker


class R4BatchAggregationEndToEndTest(unittest.TestCase):
    def setUp(self):
        self.checker = VersionedImageQualityChecker(
            minimum_laplacian_variance=5.0
        )

    def test_ten_items_with_one_quality_rejection_leave_nine_completed(self):
        qualities = [self.checker.inspect(_blade()) for _ in range(9)]
        qualities.append(
            self.checker.inspect(np.full((256, 256, 3), 100, np.uint8))
        )

        completed = sum(value.overall != "REJECTED" for value in qualities)
        rejected = sum(value.overall == "REJECTED" for value in qualities)
        self.assertEqual((completed, rejected), (9, 1))
        self.assertEqual(_aggregate(10, completed, rejected, 0), "PARTIAL")

    def test_all_failed_all_completed_and_inconclusive_are_safe(self):
        self.assertEqual(_aggregate(10, 0, 10, 0), "FAILED")
        self.assertEqual(_aggregate(10, 10, 0, 0), "COMPLETED")
        self.assertEqual(_aggregate(10, 9, 0, 1), "HOLD")


def _aggregate(total, completed, rejected, inconclusive):
    if inconclusive:
        return "HOLD"
    if rejected == total:
        return "FAILED"
    if completed == total:
        return "COMPLETED"
    return "PARTIAL"


def _blade():
    image = np.full((256, 256, 3), 80, np.uint8)
    cv2.circle(image, (128, 128), 82, (175, 175, 175), -1)
    for angle in range(0, 360, 20):
        radians = np.deg2rad(angle)
        start = (128 + int(25 * np.cos(radians)), 128 + int(25 * np.sin(radians)))
        end = (128 + int(75 * np.cos(radians)), 128 + int(75 * np.sin(radians)))
        cv2.line(image, start, end, (55, 55, 55), 2)
    return image


if __name__ == "__main__":
    unittest.main()
