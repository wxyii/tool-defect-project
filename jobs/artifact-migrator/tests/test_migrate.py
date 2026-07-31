"""P6-01 历史数据迁移任务单元测试"""

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from migrate import (
    REPO_ROOT,
    DATA_DIR,
    MANIFESTS,
    MANIFESTS_DIR,
    SampleRecord,
    ManifestSpec,
    load_manifest,
    check_cross_split_leakage,
    check_label_mask_consistency,
    check_filename_family_leakage,
    filename_family,
    sha256_hex,
)


class FilenameFamilyTests(unittest.TestCase):
    def test_simple_family(self):
        self.assertEqual(filename_family("qualified/100.png"), "qualified/100")

    def test_family_with_spaces(self):
        self.assertEqual(filename_family("qualified/22 - 4.png"), "qualified/22 - 4")

    def test_no_directory(self):
        self.assertEqual(filename_family("sample.png"), "sample")


class ManifestLoadTests(unittest.TestCase):
    def test_load_dataset_csv_sample_count(self):
        spec = MANIFESTS[0]
        records, errors = load_manifest(spec)
        self.assertEqual(len(records), 180)
        self.assertEqual(len(errors), 0)

    def test_load_retrain_csv_sample_count(self):
        spec = MANIFESTS[1]
        records, errors = load_manifest(spec)
        self.assertEqual(len(records), 172)
        self.assertEqual(len(errors), 0)

    def test_load_dataset_csv_hashes(self):
        spec = MANIFESTS[0]
        records, _ = load_manifest(spec)
        for r in records:
            self.assertIsNotNone(r.image_sha256)
            self.assertGreater(len(r.image_sha256), 0)
            self.assertGreater(r.image_size_bytes, 0)
            self.assertIsNotNone(r.mask_sha256)
            self.assertGreater(len(r.mask_sha256), 0)

    def test_load_retrain_csv_hashes(self):
        spec = MANIFESTS[1]
        records, _ = load_manifest(spec)
        for r in records:
            self.assertIsNotNone(r.image_sha256)
            self.assertGreater(len(r.image_sha256), 0)


class CrossSplitLeakageTests(unittest.TestCase):
    def test_dataset_has_cross_split_leakage(self):
        spec = MANIFESTS[0]
        records, _ = load_manifest(spec)
        issues = check_cross_split_leakage(records)
        self.assertGreater(len(issues), 0)

    def test_retrain_no_cross_split_leakage(self):
        spec = MANIFESTS[1]
        records, _ = load_manifest(spec)
        issues = check_cross_split_leakage(records)
        self.assertEqual(len(issues), 0)


class LabelMaskConsistencyTests(unittest.TestCase):
    def test_retrain_no_consistency_issues(self):
        spec = MANIFESTS[1]
        records, _ = load_manifest(spec)
        issues = check_label_mask_consistency(records)
        self.assertEqual(len(issues), 0)


class FamilyLeakageTests(unittest.TestCase):
    def test_dataset_has_family_leakage(self):
        spec = MANIFESTS[0]
        records, _ = load_manifest(spec)
        issues = check_filename_family_leakage(records)
        self.assertGreater(len(issues), 0)

    def test_retrain_no_family_leakage(self):
        spec = MANIFESTS[1]
        records, _ = load_manifest(spec)
        issues = check_filename_family_leakage(records)
        self.assertEqual(len(issues), 0)


class Sha256DeterminismTests(unittest.TestCase):
    def test_sha256_deterministic(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".bin") as f:
            f.write(b"deterministic test data for artifact migration")
            f.flush()
            path = Path(f.name)
        try:
            h1 = sha256_hex(path)
            h2 = sha256_hex(path)
            self.assertEqual(h1, h2)
        finally:
            path.unlink()


class PackageIntegrityTests(unittest.TestCase):
    def test_retrain_data_matches_audit(self):
        with open(MANIFESTS_DIR / "retrain_audit.json") as f:
            audit = json.load(f)
        spec = MANIFESTS[1]
        records, _ = load_manifest(spec)
        self.assertEqual(len(records), audit["final_samples"])
        split_counts = {}
        for r in records:
            split_counts[r.split] = split_counts.get(r.split, 0) + 1
        self.assertEqual(split_counts.get("train", 0), audit["split_counts"]["train"])
        self.assertEqual(split_counts.get("validation", 0), audit["split_counts"]["validation"])
        self.assertEqual(split_counts.get("test", 0), audit["split_counts"]["test"])
        excluded = audit["conflicting_sample_ids"]
        for r in records:
            self.assertNotIn(r.sample_id, excluded)

    def test_no_conflicting_samples_in_retrain(self):
        with open(MANIFESTS_DIR / "retrain_audit.json") as f:
            audit = json.load(f)
        spec = MANIFESTS[1]
        records, _ = load_manifest(spec)
        excluded = set(audit["conflicting_sample_ids"])
        record_ids = {r.sample_id for r in records}
        self.assertTrue(record_ids.isdisjoint(excluded))

    def test_unique_hashes_in_retrain(self):
        spec = MANIFESTS[1]
        records, _ = load_manifest(spec)
        hashes = [r.image_sha256 for r in records if r.image_sha256]
        self.assertEqual(len(hashes), len(set(hashes)))

    def test_baseline_has_duplicate_hashes(self):
        spec = MANIFESTS[0]
        records, _ = load_manifest(spec)
        hashes = [r.image_sha256 for r in records if r.image_sha256]
        self.assertGreater(len(hashes), len(set(hashes)))


class OutputConsistencyTests(unittest.TestCase):
    def test_deterministic_manifest_load(self):
        records1, errs1 = load_manifest(MANIFESTS[1])
        records2, errs2 = load_manifest(MANIFESTS[1])
        self.assertEqual(len(records1), len(records2))
        self.assertEqual(len(errs1), len(errs2))
        for r1, r2 in zip(records1, records2):
            self.assertEqual(r1.image_sha256, r2.image_sha256)
            self.assertEqual(r1.sample_id, r2.sample_id)
            self.assertEqual(r1.split, r2.split)
            self.assertEqual(r1.label, r2.label)


if __name__ == "__main__":
    unittest.main()
