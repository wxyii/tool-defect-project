import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.data.preprocess import load_image_batch, load_mask


class PreprocessTests(unittest.TestCase):
    def test_image_preprocessing_matches_grayscale_rgb_training_input(self):
        """Catches color input or missing 0..1 normalization at inference."""
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "sample.png"
            source = np.array(
                [
                    [[0, 50, 100], [100, 150, 200]],
                    [[25, 75, 125], [125, 175, 225]],
                ],
                dtype=np.uint8,
            )
            self.assertTrue(cv2.imwrite(str(image_path), source))

            batch = load_image_batch(image_path, image_size=256)

            self.assertEqual((1, 256, 256, 3), batch.shape)
            self.assertEqual(np.float32, batch.dtype)
            self.assertGreaterEqual(float(batch.min()), 0.0)
            self.assertLessEqual(float(batch.max()), 1.0)
            np.testing.assert_allclose(batch[..., 0], batch[..., 1])
            np.testing.assert_allclose(batch[..., 1], batch[..., 2])

    def test_mask_preprocessing_produces_two_class_one_hot_target(self):
        """Catches interpolated or non-binary segmentation training targets."""
        with tempfile.TemporaryDirectory() as temp_dir:
            mask_path = Path(temp_dir) / "mask.png"
            source = np.array([[0, 255], [255, 0]], dtype=np.uint8)
            self.assertTrue(cv2.imwrite(str(mask_path), source))

            mask = load_mask(mask_path, image_size=256)

            self.assertEqual((256, 256, 2), mask.shape)
            self.assertEqual(np.float32, mask.dtype)
            np.testing.assert_allclose(mask.sum(axis=-1), 1.0)
            self.assertEqual({0.0, 1.0}, set(np.unique(mask)))


if __name__ == "__main__":
    unittest.main()
