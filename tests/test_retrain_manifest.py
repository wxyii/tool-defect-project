import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tool_defect.data.retrain_manifest import (
    build_retrain_manifest,
    write_retrain_manifest,
)


def _write_source_manifest(root, samples):
    data_root = root / "data"
    rows = []
    for label_name, name, payload in samples:
        label = 0 if label_name == "qualified" else 1
        image_path = Path("images") / label_name / name
        mask_path = Path("masks") / label_name / f"{name}.png"
        absolute_image = data_root / image_path
        absolute_mask = data_root / mask_path
        absolute_image.parent.mkdir(parents=True, exist_ok=True)
        absolute_mask.parent.mkdir(parents=True, exist_ok=True)
        absolute_image.write_bytes(payload)
        absolute_mask.write_bytes(b"mask-" + name.encode("utf-8"))
        rows.append(
            {
                "sample_id": f"{label_name}/{name}",
                "image_path": image_path.as_posix(),
                "mask_path": mask_path.as_posix(),
                "annotation_path": "",
                "label": str(label),
                "label_name": label_name,
                "split": "train",
            }
        )
    manifest = root / "source.csv"
    with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return manifest, data_root


class RetrainManifestTests(unittest.TestCase):
    def test_conflicting_samples_and_exact_duplicates_are_removed(self):
        samples = []
        for label in ("qualified", "unqualified"):
            for index in range(1, 8):
                samples.append((label, f"{index}.png", f"{label}-{index}".encode()))
        samples.extend(
            [
                ("qualified", "copy.png", b"qualified-1"),
                ("unqualified", "16.png", b"unqualified-2"),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            source, data_root = _write_source_manifest(Path(temp_dir), samples)
            rows, audit = build_retrain_manifest(source, data_root, seed=1)

        ids = {row["sample_id"] for row in rows}
        self.assertNotIn("unqualified/2.png", ids)
        self.assertNotIn("unqualified/16.png", ids)
        self.assertEqual(1, sum(row["sample_id"].endswith("1.png") or row["sample_id"].endswith("copy.png") for row in rows if row["label_name"] == "qualified"))
        self.assertEqual(2, audit["excluded_conflicting"])
        self.assertEqual(1, audit["deduplicated_exact"])

    def test_related_families_and_hashes_cannot_cross_splits(self):
        samples = []
        for label in ("qualified", "unqualified"):
            for index in range(10, 24):
                samples.append((label, f"{index}.png", f"{label}-{index}".encode()))
        samples.extend(
            [
                ("qualified", "35.png", b"family-a"),
                ("qualified", "35-1.png", b"family-b"),
                ("qualified", "35 -4.png", b"family-c"),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            source, data_root = _write_source_manifest(Path(temp_dir), samples)
            first, audit = build_retrain_manifest(source, data_root, seed=1)
            second, _ = build_retrain_manifest(source, data_root, seed=1)

        self.assertEqual(first, second)
        family_splits = {
            row["split"]
            for row in first
            if row["sample_id"].startswith("qualified/35")
        }
        self.assertEqual(1, len(family_splits))
        for label in ("qualified", "unqualified"):
            self.assertEqual(
                {"train", "validation", "test"},
                {row["split"] for row in first if row["label_name"] == label},
            )
        self.assertEqual(0, audit["cross_split_duplicate_hashes"])

    def test_write_manifest_preserves_public_schema_and_audit_is_serializable(self):
        samples = [
            (label, f"{index}.png", f"{label}-{index}".encode())
            for label in ("qualified", "unqualified")
            for index in range(10, 22)
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, data_root = _write_source_manifest(root, samples)
            rows, audit = build_retrain_manifest(source, data_root, seed=1)
            destination = root / "retrain.csv"
            write_retrain_manifest(rows, destination)
            with destination.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                written = list(reader)

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
        self.assertEqual(len(rows), len(written))
        json.dumps(audit)


if __name__ == "__main__":
    unittest.main()
