import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tool_defect.training.sequence import BalancedMultitaskSequence


def _make_dataset(root):
    rows = []
    pattern = np.zeros((8, 8), dtype=np.uint8)
    pattern[1:4, 2:6] = 255
    for label_name, label, count in (
        ("qualified", 0, 3),
        ("unqualified", 1, 2),
    ):
        for index in range(count):
            image_rel = Path("images") / label_name / f"{index}.png"
            mask_rel = Path("masks") / label_name / f"{index}.png"
            image_path = root / image_rel
            mask_path = root / mask_rel
            image_path.parent.mkdir(parents=True, exist_ok=True)
            mask_path.parent.mkdir(parents=True, exist_ok=True)
            mask = pattern if label else np.zeros_like(pattern)
            Image.fromarray(np.repeat(mask[..., None], 3, axis=-1)).save(image_path)
            Image.fromarray(mask).save(mask_path)
            rows.append(
                {
                    "sample_id": f"{label_name}/{index}.png",
                    "image_path": image_rel.as_posix(),
                    "mask_path": mask_rel.as_posix(),
                    "annotation_path": "",
                    "label": str(label),
                    "label_name": label_name,
                    "split": "train",
                }
            )
    manifest = root / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return manifest


class TrainingSequenceTests(unittest.TestCase):
    def test_balanced_training_batch_has_one_sample_from_each_class(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            manifest = _make_dataset(data_root)
            sequence = BalancedMultitaskSequence(
                manifest,
                data_root,
                split="train",
                image_size=8,
                batch_size=2,
                seed=1,
                augment=False,
                balanced=True,
            )
            images, targets = sequence[0]

        self.assertEqual((2, 8, 8, 3), images.shape)
        self.assertEqual((2, 2), targets["cla_out"].shape)
        self.assertEqual([0, 1], sorted(np.argmax(targets["cla_out"], axis=1)))
        self.assertEqual((2, 8, 8, 2), targets["seg_out"].shape)
        self.assertEqual(np.float32, images.dtype)

    def test_geometry_is_synchronized_between_image_and_mask(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            manifest = _make_dataset(data_root)
            sequence = BalancedMultitaskSequence(
                manifest,
                data_root,
                split="train",
                image_size=8,
                batch_size=2,
                seed=9,
                augment=True,
                photometric=False,
                balanced=True,
            )
            images, targets = sequence[0]

        defect_index = int(
            np.flatnonzero(np.argmax(targets["cla_out"], axis=1) == 1)[0]
        )
        image_foreground = images[defect_index, ..., 0] > 0.5
        mask_foreground = targets["seg_out"][defect_index, ..., 1] > 0.5
        np.testing.assert_array_equal(image_foreground, mask_foreground)

    def test_unaugmented_sequence_is_repeatable_and_does_not_oversample(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            manifest = _make_dataset(data_root)
            sequence = BalancedMultitaskSequence(
                manifest,
                data_root,
                split="train",
                image_size=8,
                batch_size=2,
                seed=1,
                augment=False,
                balanced=False,
            )
            first_images, first_targets = sequence[0]
            second_images, second_targets = sequence[0]

        self.assertEqual(3, len(sequence))
        np.testing.assert_array_equal(first_images, second_images)
        np.testing.assert_array_equal(
            first_targets["seg_out"], second_targets["seg_out"]
        )


if __name__ == "__main__":
    unittest.main()
