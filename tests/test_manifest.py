import csv
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.data.manifest import build_manifest, write_manifest


class ManifestTests(unittest.TestCase):
    def _make_dataset(self, root: Path, count_per_class: int = 5) -> None:
        for relative in (
            "images/qualified",
            "images/unqualified",
            "masks/qualified",
            "masks/unqualified",
            "annotations/labelme_json",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)

        for index in range(count_per_class):
            qualified_name = f"q{index}.jpg"
            unqualified_name = f"u{index}.png"
            (root / "images/qualified" / qualified_name).write_bytes(b"image")
            (root / "images/unqualified" / unqualified_name).write_bytes(b"image")
            # The supplied qualified masks use the original extension plus ".png".
            (root / "masks/qualified" / f"{qualified_name}.png").write_bytes(b"mask")
            (root / "masks/unqualified" / f"u{index}.png").write_bytes(b"mask")
            (root / "annotations/labelme_json" / f"u{index}.json").write_text(
                "{}", encoding="utf-8"
            )

    def test_build_manifest_pairs_double_extension_masks_and_stratifies_split(self):
        """Catches broken mask stem normalization or non-stratified validation data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            self._make_dataset(data_root)

            rows = build_manifest(
                data_root,
                validation_fraction=0.2,
                test_fraction=0.2,
                seed=1,
            )

            self.assertEqual(10, len(rows))
            qualified = [row for row in rows if row.label_name == "qualified"]
            unqualified = [row for row in rows if row.label_name == "unqualified"]
            self.assertEqual(5, len(qualified))
            self.assertEqual(5, len(unqualified))
            self.assertEqual(1, sum(row.split == "validation" for row in qualified))
            self.assertEqual(1, sum(row.split == "validation" for row in unqualified))
            self.assertEqual(1, sum(row.split == "test" for row in qualified))
            self.assertEqual(1, sum(row.split == "test" for row in unqualified))
            self.assertEqual(3, sum(row.split == "train" for row in qualified))
            self.assertEqual(3, sum(row.split == "train" for row in unqualified))
            self.assertTrue(all(row.mask_path.endswith(".jpg.png") for row in qualified))
            self.assertTrue(all(row.annotation_path == "" for row in qualified))
            self.assertTrue(all(row.annotation_path.endswith(".json") for row in unqualified))

    def test_build_manifest_rejects_an_image_without_a_mask(self):
        """Catches silent training with an image whose segmentation target is missing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            self._make_dataset(data_root, count_per_class=2)
            (data_root / "masks/unqualified/u1.png").unlink()

            with self.assertRaisesRegex(ValueError, "missing mask"):
                build_manifest(data_root, validation_fraction=0.2, seed=1)

    def test_build_manifest_pairs_jpg_image_with_stem_png_mask(self):
        """Catches the supplied unqualified JPG-to-PNG mask naming convention."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            self._make_dataset(data_root, count_per_class=2)
            original_image = data_root / "images/unqualified/u1.png"
            jpg_image = original_image.with_suffix(".jpg")
            original_image.rename(jpg_image)

            rows = build_manifest(data_root, validation_fraction=0.2, seed=1)

            row = next(item for item in rows if item.image_path.endswith("u1.jpg"))
            self.assertEqual("masks/unqualified/u1.png", row.mask_path)

    def test_qualified_image_never_inherits_same_stem_unqualified_annotation(self):
        """Catches cross-class annotation leakage for duplicate source basenames."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            self._make_dataset(data_root, count_per_class=2)
            qualified = data_root / "images/qualified/q1.jpg"
            qualified.rename(data_root / "images/qualified/u1.jpg")
            (data_root / "masks/qualified/q1.jpg.png").rename(
                data_root / "masks/qualified/u1.jpg.png"
            )

            rows = build_manifest(data_root, validation_fraction=0.2, seed=1)

            qualified_row = next(
                item
                for item in rows
                if item.label_name == "qualified"
                and item.image_path.endswith("u1.jpg")
            )
            self.assertEqual("", qualified_row.annotation_path)

    def test_write_manifest_emits_stable_public_columns(self):
        """Catches a CSV schema change that would break training and evaluation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            self._make_dataset(data_root, count_per_class=2)
            rows = build_manifest(data_root, validation_fraction=0.2, seed=1)
            destination = data_root / "manifests/dataset.csv"

            write_manifest(rows, destination)

            with destination.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(
                    [
                        "sample_id",
                        "image_path",
                        "mask_path",
                        "annotation_path",
                        "label",
                        "label_name",
                        "split",
                    ],
                    reader.fieldnames,
                )
                self.assertEqual(4, len(list(reader)))


if __name__ == "__main__":
    unittest.main()
