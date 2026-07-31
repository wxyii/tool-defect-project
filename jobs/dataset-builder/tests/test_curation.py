#!/usr/bin/env python3
"""P6-02 数据集准入、去重和不可变版本测试。"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_ROOT))

import curation  # noqa: E402
import verify_p6_02  # noqa: E402


class CurationTest(unittest.TestCase):
    def setUp(self) -> None:
        if curation.Image is None:
            self.skipTest("Pillow unavailable")

    def _write_image(self, path: Path, inverted: bool = False) -> None:
        image = curation.Image.new("L", (16, 16), 0 if not inverted else 255)
        pixels = image.load()
        for y in range(16):
            for x in range(16):
                if (not inverted and (x + y) % 2 == 0) or (inverted and x < 8):
                    pixels[x, y] = 255 if not inverted else 0
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG")

    def _write_mask(self, path: Path, positive: bool) -> None:
        mask = curation.Image.new("L", (16, 16), 0)
        if positive:
            for y in range(4, 12):
                for x in range(4, 12):
                    mask.putpixel((x, y), 255)
        path.parent.mkdir(parents=True, exist_ok=True)
        mask.save(path, format="PNG")

    def _write_manifest(self, path: Path, rows: list[dict[str, str]]) -> None:
        columns = [
            "sample_key", "image_path", "mask_path", "label", "label_name", "split", "group_key",
            "source", "source_license_state", "review_state", "quality_state", "difficulty",
            "capture_id", "source_review_id",
        ]
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    def _valid_rows(self) -> list[dict[str, str]]:
        return [
            {
                "sample_key": "normal/one.png", "image_path": "images/normal-one.png", "mask_path": "masks/normal-one.png",
                "label": "0", "label_name": "qualified", "split": "train", "group_key": "normal-one",
                "source": "source-A", "source_license_state": "APPROVED", "review_state": "CLOSED",
                "quality_state": "APPROVED", "difficulty": "NORMAL", "capture_id": "capture-one",
                "source_review_id": "review-one",
            },
            {
                "sample_key": "hard/two.png", "image_path": "images/hard-two.png", "mask_path": "masks/hard-two.png",
                "label": "1", "label_name": "unqualified", "split": "train", "group_key": "hard-two",
                "source": "source-B", "source_license_state": "APPROVED", "review_state": "CLOSED",
                "quality_state": "APPROVED", "difficulty": "HARD", "capture_id": "capture-two",
                "source_review_id": "review-two",
            },
        ]

    def test_sample_id_is_accepted_but_missing_evidence_blocks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p6-02-load-") as temp:
            root = Path(temp)
            data_root = root / "data"
            old_data_dir = curation.DATA_DIR
            try:
                curation.DATA_DIR = data_root
                self._write_image(data_root / "images/a.png")
                self._write_mask(data_root / "masks/a.png", False)
                manifest = root / "candidate.csv"
                row = self._valid_rows()[0]
                row.pop("sample_key")
                row["sample_id"] = "legacy/a.png"
                row["image_path"] = "images/a.png"
                row["mask_path"] = "masks/a.png"
                row["source_license_state"] = ""
                row["review_state"] = ""
                self._write_manifest_with_columns(manifest, row)
                samples, errors = curation.load_candidate_manifest(manifest)
                self.assertEqual([], errors)
                self.assertEqual("legacy/a.png", samples[0].sample_key)
                issues = curation.validate_candidate_metadata(samples)
                self.assertIn("source_license", issues)
            finally:
                curation.DATA_DIR = old_data_dir

    def _write_manifest_with_columns(self, path: Path, row: dict[str, str]) -> None:
        columns = list(row.keys())
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerow(row)

    def test_positive_empty_mask_and_approximate_cross_split_are_blockers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p6-02-audit-") as temp:
            root = Path(temp)
            data_root = root / "data"
            old_data_dir = curation.DATA_DIR
            try:
                curation.DATA_DIR = data_root
                self._write_image(data_root / "images/a.png")
                self._write_image(data_root / "images/b.png", inverted=True)
                self._write_mask(data_root / "masks/a.png", False)
                self._write_mask(data_root / "masks/b.png", False)
                rows = self._valid_rows()
                rows[0].update({"image_path": "images/a.png", "mask_path": "masks/a.png", "difficulty": "NORMAL"})
                rows[1].update({"image_path": "images/b.png", "mask_path": "masks/b.png", "difficulty": "HARD", "split": "validation", "label": "1"})
                manifest = root / "candidate.csv"
                self._write_manifest(manifest, rows)
                samples, load_errors = curation.load_candidate_manifest(manifest)
                self.assertEqual([], load_errors)
                issues = curation.validate_candidate_metadata(samples)
                self.assertTrue(any("positive_empty_mask" in item for item in issues["sample_integrity"]))
                samples[0].perceptual_hash = 0
                samples[1].perceptual_hash = 1
                pairs = curation.approximate_duplicate_pairs(samples)
                self.assertEqual(1, len(pairs))
                self.assertNotEqual(samples[0].split, samples[1].split)
            finally:
                curation.DATA_DIR = old_data_dir

    def test_valid_version_has_two_classes_of_difficulty_and_can_be_verified_after_independent_approval(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p6-02-valid-") as temp:
            root = Path(temp)
            data_root = root / "data"
            old_data_dir = curation.DATA_DIR
            try:
                curation.DATA_DIR = data_root
                self._write_image(data_root / "images/normal-one.png", inverted=False)
                self._write_image(data_root / "images/hard-two.png", inverted=True)
                self._write_mask(data_root / "masks/normal-one.png", positive=False)
                self._write_mask(data_root / "masks/hard-two.png", positive=True)
                candidate = root / "candidate.csv"
                parent = root / "parent.csv"
                rows = self._valid_rows()
                self._write_manifest(candidate, rows)
                parent_rows = []
                for row in rows:
                    parent_row = dict(row)
                    parent_row["sample_key"] = parent_row.pop("sample_key")
                    parent_rows.append(parent_row)
                self._write_manifest(parent, parent_rows)
                samples, load_errors = curation.load_candidate_manifest(candidate)
                self.assertEqual([], load_errors)
                package = root / "controlled" / "production-candidate-v1"
                report = curation.build_dataset(samples, candidate, parent, "production-candidate-v1", "test", package)
                self.assertEqual("COMPLETE", report["status"])
                self.assertEqual(2, report["accepted_samples"])
                approval_path = package / "approval.json"
                approval = json.loads(approval_path.read_text(encoding="utf-8"))
                approval.update({
                    "state": "APPROVED", "approved_by": "quality-lead", "approved_at": "2026-07-31T00:00:00Z",
                    "independent_approver": True,
                })
                approval_path.write_text(json.dumps(approval), encoding="utf-8")
                result = verify_p6_02.verify_version(package)
                self.assertEqual("COMPLETE", result["status"], result)
                self.assertEqual(2, result["accepted_samples"])
                self.assertEqual(4, len((package / "checksums.sha256").read_text(encoding="utf-8").splitlines()))
            finally:
                curation.DATA_DIR = old_data_dir

    def test_existing_package_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p6-02-immutable-") as temp:
            package = Path(temp) / "controlled" / "production-candidate-v1"
            package.mkdir(parents=True)
            (package / "sentinel").write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                curation.build_dataset([], Path(temp) / "candidate.csv", Path(temp) / "parent.csv", "production-candidate-v1", "test", package)


if __name__ == "__main__":
    unittest.main(verbosity=2)
