import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tool_defect.data.circular_slice_dataset import (
    annular_sector_mask,
    build_adaptive_annular_slice_dataset,
    build_circular_slice_dataset,
    circular_slice,
)


def _write_png(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError(path)
    encoded.tofile(str(path))


class CircularSliceDatasetTests(unittest.TestCase):
    def test_circular_slice_wraps_without_padding(self):
        source = np.arange(16, dtype=np.uint8)[None, :]
        result = circular_slice(source, 14, 4)
        np.testing.assert_array_equal(result, [[14, 15, 0, 1]])

    def test_annular_sector_mask_wraps_at_zero_degrees(self):
        sector = annular_sector_mask((8, 8), (4, 4), 315, 90)

        self.assertTrue(sector[4, 7])
        self.assertTrue(sector[1, 7])
        self.assertFalse(sector[7, 4])

    def _make_source_dataset(self, root):
        data_root = Path(root) / "boundary_normalized"
        rows = []
        specs = (
            ("qualified", 0, "train", np.zeros((4, 16), dtype=np.uint8)),
            ("unqualified", 1, "validation", None),
        )
        for label_name, label, split, mask in specs:
            image = np.zeros((4, 16, 3), dtype=np.uint8)
            for column in range(16):
                image[:, column, :] = column
            if mask is None:
                mask = np.zeros((4, 16), dtype=np.uint8)
                mask[:, 15] = 255
            image_relative = Path("images") / label_name / "1.png"
            mask_relative = Path("masks") / label_name / "1.png"
            _write_png(data_root / image_relative, image)
            _write_png(data_root / mask_relative, mask)
            rows.append(
                {
                    "sample_id": f"{label_name}/1.png",
                    "image_path": image_relative.as_posix(),
                    "mask_path": mask_relative.as_posix(),
                    "annotation_path": "",
                    "label": label,
                    "label_name": label_name,
                    "split": split,
                }
            )
        manifest = data_root / "manifests" / "dataset.csv"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return data_root, manifest

    def test_builds_eight_overlapping_patches_and_derives_labels(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root, source_manifest = self._make_source_dataset(temp_dir)
            output_root = Path(temp_dir) / "boundary_normalized_8patch"
            report = build_circular_slice_dataset(
                source_root,
                source_manifest,
                output_root,
                slice_count=8,
                window_degrees=90,
                stride_degrees=45,
            )

            self.assertEqual("complete", report["status"])
            self.assertEqual(16, report["generated_samples"])
            self.assertEqual([4, 4], report["patch_shape"])
            self.assertEqual(
                {"qualified": 14, "unqualified": 2},
                report["patch_label_counts"],
            )
            with (output_root / "manifests/dataset.csv").open(
                newline="", encoding="utf-8-sig"
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(16, len(rows))
            self.assertEqual(
                {"train", "validation"},
                {row["split"] for row in rows},
            )

            with (output_root / "manifests/provenance.csv").open(
                newline="", encoding="utf-8-sig"
            ) as handle:
                provenance = list(csv.DictReader(handle))
            self.assertEqual(16, len(provenance))
            self.assertEqual(
                {"true"},
                {
                    row["wraps_seam"]
                    for row in provenance
                    if row["patch_index"] == "7"
                },
            )
            self.assertEqual(
                {"qualified", "unqualified"},
                {row["label_name"] for row in provenance},
            )
            child_mask_paths = [
                output_root / row["mask_path"] for row in rows
            ]
            self.assertTrue(all(path.is_file() for path in child_mask_paths))

    def test_failure_writes_report_but_no_training_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root, source_manifest = self._make_source_dataset(temp_dir)
            bad_mask = source_root / "masks/qualified/1.png"
            _write_png(bad_mask, np.zeros((3, 16), dtype=np.uint8))
            output_root = Path(temp_dir) / "failed_output"
            with self.assertRaisesRegex(RuntimeError, "生成失败"):
                build_circular_slice_dataset(
                    source_root,
                    source_manifest,
                    output_root,
                )
            self.assertTrue((output_root / "generation_report.json").is_file())
            self.assertFalse(
                (output_root / "manifests/dataset.csv").exists()
            )
            report = json.loads(
                (output_root / "generation_report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("failed", report["status"])
            self.assertEqual(1, report["failed_samples"])

    def test_builds_adaptive_annular_full_size_sectors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "adaptive_annular"
            rows = []
            for label_name, label, split in (
                ("qualified", 0, "train"),
                ("unqualified", 1, "validation"),
            ):
                image = np.zeros((32, 32, 3), dtype=np.uint8)
                image[:, :, 0] = np.arange(32, dtype=np.uint8)[None, :]
                mask = np.zeros((32, 32), dtype=np.uint8)
                if label:
                    mask[16, 31] = 255
                    image[16, 31] = (255, 255, 255)
                image_relative = Path("images") / label_name / "1.png"
                mask_relative = Path("masks") / label_name / "1.png"
                _write_png(data_root / image_relative, image)
                _write_png(data_root / mask_relative, mask)
                rows.append(
                    {
                        "sample_id": f"{label_name}/1.png",
                        "image_path": image_relative.as_posix(),
                        "mask_path": mask_relative.as_posix(),
                        "annotation_path": "",
                        "label": label,
                        "label_name": label_name,
                        "split": split,
                    }
                )
            manifest = data_root / "manifests" / "dataset.csv"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            with manifest.open(
                "w", newline="", encoding="utf-8-sig"
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

            output_root = Path(temp_dir) / "adaptive_annular_8patch"
            report = build_adaptive_annular_slice_dataset(
                data_root,
                manifest,
                output_root,
            )

            self.assertEqual("complete", report["status"])
            self.assertEqual(16, report["generated_samples"])
            self.assertEqual([32, 32], report["patch_shape"])
            self.assertEqual(
                {"qualified": 14, "unqualified": 2},
                report["patch_label_counts"],
            )
            with (output_root / "manifests/dataset.csv").open(
                newline="", encoding="utf-8-sig"
            ) as handle:
                generated = list(csv.DictReader(handle))
            positive = [
                row
                for row in generated
                if row["label_name"] == "unqualified"
            ]
            self.assertEqual(2, len(positive))
            for row in positive:
                mask = cv2.imdecode(
                    np.fromfile(output_root / row["mask_path"], dtype=np.uint8),
                    cv2.IMREAD_GRAYSCALE,
                )
                self.assertEqual(255, int(mask[16, 31]))
                self.assertEqual(1, int(np.count_nonzero(mask)))

            with (output_root / "manifests/provenance.csv").open(
                newline="", encoding="utf-8-sig"
            ) as handle:
                provenance = list(csv.DictReader(handle))
            self.assertEqual(16, len(provenance))
            self.assertEqual(
                {"true"},
                {
                    row["wraps_seam"]
                    for row in provenance
                    if row["patch_index"] == "7"
                },
            )


if __name__ == "__main__":
    unittest.main()
