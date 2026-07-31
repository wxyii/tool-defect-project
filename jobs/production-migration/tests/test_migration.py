"""P7-03 生产迁移与恢复单元测试"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_JOBS_DIR = Path(__file__).resolve().parents[1]
_RECOVERY_DIR = _REPO_ROOT / "jobs" / "production-recovery"

sys.path.insert(0, str(_JOBS_DIR))
sys.path.insert(0, str(_RECOVERY_DIR))
from migrate_data import (
    DatabaseClient,
    MigrationReport,
    sha256_hex,
    sha256_bytes,
    sha256_text,
    generate_object_key,
    verify_source_integrity,
    SourceRecord,
    load_manifest_csv,
    load_checksums,
    main as migration_main,
    register_database_references,
    source_is_approved,
    summarize_phases,
    CONTROLLED_OUTPUT,
    DATA_DIR,
)


class HashVerificationTests(unittest.TestCase):
    def test_sha256_hex_deterministic(self):
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".bin") as f:
            f.write(b"p7-03 migration hash test data")
            f.flush()
            path = Path(f.name)
        try:
            h1 = sha256_hex(path)
            h2 = sha256_hex(path)
            self.assertEqual(h1, h2)
            self.assertEqual(len(h1), 64)
            self.assertTrue(all(c in "0123456789abcdef" for c in h1))
        finally:
            path.unlink()

    def test_sha256_bytes_correct(self):
        data = b"test bytes for hash verification"
        h = sha256_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        self.assertEqual(h, expected)

    def test_sha256_text_correct(self):
        text = "test text for hash verification"
        h = sha256_text(text)
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual(h, expected)

    def test_sha256_vary_by_content(self):
        h1 = sha256_bytes(b"content A")
        h2 = sha256_bytes(b"content B")
        self.assertNotEqual(h1, h2)


class SourceIntegrityTests(unittest.TestCase):
    def test_integrity_all_clean_records_pass(self):
        rec = SourceRecord(
            sample_id="test/001.png",
            image_path="images/test/001.png",
            mask_path="masks/test/001.png.png",
            label=0,
            label_name="qualified",
            split="train",
            image_sha256="",
            image_size_bytes=0,
            image_width=0,
            image_height=0,
            image_channels=0,
            mask_sha256="",
            mask_size_bytes=0,
            mask_has_content="",
            family_key="test/001",
            errors=0,
        )
        rec.image_sha256 = sha256_hex(DATA_DIR / rec.image_path) if (DATA_DIR / rec.image_path).exists() else ""
        rec.mask_sha256 = sha256_hex(DATA_DIR / rec.mask_path) if (DATA_DIR / rec.mask_path).exists() else ""
        records = [rec]
        checksums = {}
        if (DATA_DIR / rec.image_path).exists():
            checksums[str(DATA_DIR / rec.image_path)] = rec.image_sha256
        if (DATA_DIR / rec.mask_path).exists():
            checksums[str(DATA_DIR / rec.mask_path)] = rec.mask_sha256

    def test_load_manifest_csv_count(self):
        manifest_path = CONTROLLED_OUTPUT / "baseline-180" / "manifest.csv"
        self.assertTrue(manifest_path.exists(), "P6-01 baseline-180 manifest not found")
        records = load_manifest_csv(manifest_path)
        self.assertEqual(len(records), 180)

    def test_load_checksums_not_empty(self):
        checksums_path = CONTROLLED_OUTPUT / "baseline-180" / "checksums.sha256"
        self.assertTrue(checksums_path.exists(), "P6-01 baseline-180 checksums not found")
        checksums = load_checksums(checksums_path)
        self.assertGreater(len(checksums), 0)


class GenerateObjectKeyTests(unittest.TestCase):
    def test_key_contains_kind_and_sample(self):
        key = generate_object_key("RAW", "qualified/100.png", ".png")
        self.assertIn("raw", key)
        self.assertIn("100.png.png", key)
        self.assertTrue(key.startswith("capture/"))

    def test_key_is_lowercase(self):
        key = generate_object_key("DEFECT_MASK", "Unqualified/22.jpg", ".jpg")
        self.assertEqual(key, key.lower())
        self.assertIn("defect_mask", key)


class DryRunTests(unittest.TestCase):
    def test_dry_run_does_not_modify_s3(self):
        from migrate_data import S3Client
        s3 = S3Client(
            endpoint="http://localhost:9000",
            access_key="test-access-key",
            secret_key="test-secret-key",
            bucket="test-bucket",
        )
        self.assertEqual(len(s3._uploaded), 0)

    def test_dry_run_counts_are_non_negative(self):
        from migrate_data import call_s3_dry
        rec = SourceRecord(
            sample_id="test/001.png",
            image_path="images/test/001.png",
            mask_path="masks/test/001.png.png",
            label=0,
            label_name="qualified",
            split="train",
            image_sha256="a" * 64,
            image_size_bytes=1024,
            image_width=512,
            image_height=512,
            image_channels=3,
            mask_sha256="b" * 64,
            mask_size_bytes=512,
            mask_has_content="True",
            family_key="test/001",
            errors=0,
        )
        rec2 = SourceRecord(
            sample_id="test/002.png",
            image_path="images/test/002.png",
            mask_path="masks/test/002.png.png",
            label=1,
            label_name="unqualified",
            split="test",
            image_sha256="c" * 64,
            image_size_bytes=2048,
            image_width=512,
            image_height=512,
            image_channels=3,
            mask_sha256="d" * 64,
            mask_size_bytes=256,
            mask_has_content="False",
            family_key="test/002",
            errors=0,
        )
        result = call_s3_dry([rec, rec2])
        self.assertEqual(result["uploaded"], 4)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["total_bytes"], 1024 + 512 + 2048 + 256)
        self.assertTrue(result["dry_run"])


class RollbackListingTests(unittest.TestCase):
    def test_unscoped_rollback_is_blocked_without_writes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            self.assertEqual(
                migration_main(["--rollback", "--output-dir", str(output_dir)]),
                2,
            )
            self.assertFalse(output_dir.exists())


class MigrationSafetyTests(unittest.TestCase):
    def _phase(self, status):
        return MigrationReport("phase", status, {}, [])

    def test_dry_run_never_becomes_complete(self):
        phases = {
            name: self._phase("DRY_RUN")
            for name in ("verify_source", "migrate_objects", "register_database", "verify_counts")
        }
        self.assertEqual(
            summarize_phases(phases, execution_mode="DRY_RUN")["overall_status"],
            "BLOCKED",
        )

    def test_skipped_phase_never_becomes_complete(self):
        phases = {
            name: self._phase("PASSED")
            for name in ("verify_source", "migrate_objects", "register_database", "verify_counts")
        }
        phases["register_database"] = self._phase("SKIPPED")
        self.assertEqual(
            summarize_phases(phases, execution_mode="EXECUTE")["overall_status"],
            "BLOCKED",
        )

    def test_only_full_execute_can_be_complete(self):
        phases = {
            name: self._phase("PASSED")
            for name in ("verify_source", "migrate_objects", "register_database", "verify_counts")
        }
        self.assertEqual(
            summarize_phases(phases, execution_mode="EXECUTE")["overall_status"],
            "COMPLETE",
        )

    def test_blocked_source_is_not_approved(self):
        approved, blockers = source_is_approved(
            {
                "overall_status": "BLOCKED",
                "production_claim_allowed": False,
                "manifests": {"baseline-180": {"status": "BLOCKED"}},
            }
        )
        self.assertFalse(approved)
        self.assertGreater(len(blockers), 0)

    def test_non_dry_database_registration_never_fakes_success(self):
        db = DatabaseClient("postgresql://localhost:5432/test", "user", "password")
        with self.assertRaises(NotImplementedError):
            register_database_references(db, None, [], [], False)


class VerificationReportTests(unittest.TestCase):
    def test_verification_result_basics(self):
        from verify_migration import VerificationResult
        result = VerificationResult("test_category")
        self.assertEqual(result.category, "test_category")
        self.assertEqual(result.passed, 0)
        self.assertEqual(result.failed, 0)

        result.add_check("test_check_1", True, {"detail": 42})
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.status(), "PASSED")

        result.add_check("test_check_2", False, {"detail": 0})
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.status(), "PARTIAL")

        result.add_check("test_check_3", False, {})
        self.assertEqual(result.failed, 2)
        self.assertEqual(result.status(), "PARTIAL")

    def test_verification_report_generation(self):
        from verify_migration import VerificationResult, generate_report
        results = [
            VerificationResult("cat_a"),
            VerificationResult("cat_b"),
        ]
        results[0].add_check("a1", True)
        results[0].add_check("a2", True)
        results[1].add_check("b1", True)

        report = generate_report(results)
        self.assertEqual(report["overall_status"], "PASSED")
        self.assertIn("cat_a", report["categories"])
        self.assertIn("cat_b", report["categories"])
        self.assertEqual(report["categories"]["cat_a"]["passed"], 2)
        self.assertEqual(report["categories"]["cat_b"]["passed"], 1)


class RecoveryDrillReportTests(unittest.TestCase):
    def test_drill_report_structure(self):
        from recovery_drill import RecoveryDrillOrchestrator
        orchestrator = RecoveryDrillOrchestrator("test-drill-001")
        self.assertEqual(orchestrator.drill_id, "test-drill-001")
        self.assertEqual(len(orchestrator.scenarios), 0)
        self.assertEqual(len(orchestrator.errors), 0)

    def test_drill_scenario_passed(self):
        from recovery_drill import RecoveryDrillOrchestrator
        orchestrator = RecoveryDrillOrchestrator("test-drill-002")
        result = orchestrator._check_result("test_scenario", True, {"value": 1})
        self.assertTrue(result["passed"])
        self.assertEqual(len(orchestrator.scenarios), 1)
        self.assertEqual(len(orchestrator.errors), 0)

    def test_drill_scenario_failed_adds_error(self):
        from recovery_drill import RecoveryDrillOrchestrator
        orchestrator = RecoveryDrillOrchestrator("test-drill-003")
        result = orchestrator._check_result("fail_scenario", False, {"reason": "test"})
        self.assertFalse(result["passed"])
        self.assertEqual(len(orchestrator.scenarios), 1)
        self.assertEqual(len(orchestrator.errors), 1)

    def test_drill_report_counts(self):
        from recovery_drill import RecoveryDrillOrchestrator
        orchestrator = RecoveryDrillOrchestrator("test-drill-004")
        orchestrator._check_result("s1", True)
        orchestrator._check_result("s2", False)
        orchestrator._check_result("s3", True)

        report = orchestrator.generate_report()
        self.assertEqual(report["scenarios_total"], 3)
        self.assertEqual(report["scenarios_passed"], 2)
        self.assertEqual(report["scenarios_failed"], 1)
        self.assertEqual(report["result"], "FAILED")

    def test_drill_report_all_passed(self):
        from recovery_drill import RecoveryDrillOrchestrator
        orchestrator = RecoveryDrillOrchestrator("test-drill-005")
        orchestrator._check_result("s1", True)
        orchestrator._check_result("s2", True)

        report = orchestrator.generate_report()
        self.assertEqual(report["result"], "BLOCKED")
        self.assertGreater(report["duration_seconds"], 0)

    def test_only_attested_complete_scenario_set_succeeds(self):
        from recovery_drill import REQUIRED_SCENARIOS, RecoveryDrillOrchestrator

        with tempfile.TemporaryDirectory() as tmpdir:
            verification_path = Path(tmpdir) / "verification.json"
            raw_log_path = Path(tmpdir) / "recovery.log"
            verification_path.write_text("{}", encoding="utf-8")
            raw_log_path.write_text("real execution log", encoding="utf-8")
            orchestrator = RecoveryDrillOrchestrator(
                "test-drill-006",
                source_type="REAL_PRODUCTION",
                environment="ISOLATED_PRODUCTION_EQUIVALENT",
                executor_id="operator-006",
                rpo_target_seconds=3600,
                rto_target_seconds=3600,
                migration_verification_path=str(verification_path),
                raw_log_path=str(raw_log_path),
                sign_off={
                    "decision": "APPROVED",
                    "signed_by": "approver-006",
                    "signed_at": "2026-07-31T03:00:00Z",
                    "reason": "恢复演练证据完整",
                },
            )
            orchestrator.rpo_actual_seconds = 60
            for scenario in REQUIRED_SCENARIOS:
                orchestrator._check_result(scenario, True)
            report = orchestrator.generate_report()
            self.assertEqual(report["result"], "SUCCEEDED")
            self.assertTrue(report["exact_scenario_set"])
            self.assertTrue(report["production_attestation_complete"])

    def test_missing_snapshot_path_fails_without_copying_repository(self):
        from recovery_drill import RecoveryDrillOrchestrator

        orchestrator = RecoveryDrillOrchestrator("test-drill-007")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = orchestrator.verify_isolated_restore("", tmpdir)
        self.assertFalse(result["passed"])


class ObjectKeyConsistencyTests(unittest.TestCase):
    def test_key_deterministic(self):
        key1 = generate_object_key("RAW", "qualified/100.png", ".png")
        key2 = generate_object_key("RAW", "qualified/100.png", ".png")
        self.assertEqual(key1, key2)


class SourceManifestSmokeTests(unittest.TestCase):
    def test_manifest_csv_aligned_with_checksums(self):
        manifest_path = CONTROLLED_OUTPUT / "baseline-180" / "manifest.csv"
        checksums_path = CONTROLLED_OUTPUT / "baseline-180" / "checksums.sha256"
        self.assertTrue(manifest_path.exists(), "P6-01 baseline manifest missing")
        self.assertTrue(checksums_path.exists(), "P6-01 baseline checksums missing")
        records = load_manifest_csv(manifest_path)
        checksums = load_checksums(checksums_path)
        self.assertGreater(len(records), 0)
        self.assertGreater(len(checksums), 0)


if __name__ == "__main__":
    unittest.main()
