import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.data.datasets import load_dataset
from tool_defect.models.generator import CustomDataGenerator


class DatasetTests(unittest.TestCase):
    def test_real_manifest_loads_bound_images_labels_and_masks(self):
        """Catches training arrays becoming independently ordered or mis-shaped."""
        manifest = PROJECT_ROOT / "data/manifests/curated_v1_retrain.csv"
        with manifest.open(encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        split = rows[0]["split"]

        images, labels, masks = load_dataset(
            manifest,
            data_root=PROJECT_ROOT / "data",
            split=split,
            image_size=256,
            max_samples=2,
            include_masks=True,
        )

        self.assertEqual((2, 256, 256, 3), images.shape)
        self.assertEqual((2, 2), labels.shape)
        self.assertEqual((2, 256, 256, 2), masks.shape)
        np.testing.assert_allclose(labels.sum(axis=-1), 1.0)
        np.testing.assert_allclose(masks.sum(axis=-1), 1.0)

    def test_generator_returns_classification_then_segmentation_targets(self):
        """Catches reversed multi-output targets during training."""
        images = np.zeros((2, 8, 8, 3), dtype=np.float32)
        labels = np.eye(2, dtype=np.float32)
        masks = np.zeros((2, 8, 8, 2), dtype=np.float32)
        masks[..., 0] = 1.0
        generator = CustomDataGenerator(
            images,
            labels,
            masks,
            batch_size=2,
            shuffle=False,
            augmentations=None,
        )

        batch_images, targets = generator[0]

        self.assertEqual((2, 8, 8, 3), batch_images.shape)
        self.assertEqual((2, 2), targets["cla_out"].shape)
        self.assertEqual((2, 8, 8, 2), targets["seg_out"].shape)


if __name__ == "__main__":
    unittest.main()
