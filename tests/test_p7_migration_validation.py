"""P7-03 迁移与恢复严格证据单元测试。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.p7.common import sha256_file
from tools.p7.migration import (
    REQUIRED_ARTIFACT_GROUPS,
    REQUIRED_PHASES,
    REQUIRED_RECOVERY_SCENARIOS,
    validate_migration_report,
    validate_migration_verification,
    validate_p7_03_evidence,
    validate_recovery_report,
)


class P7MigrationValidationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.evidence = self.root / "deploy/environments/production/evidence"
        self.evidence.mkdir(parents=True)

    def tearDown(self):
        self._temp.cleanup()

    def _file_evidence(self, name: str, content: str = "immutable evidence\n") -> tuple[str, str]:
        path = self.evidence / name
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.root)), sha256_file(path)

    def _write_json(self, name: str, value: dict) -> Path:
        path = self.evidence / name
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return path

    def _valid_reports(self) -> tuple[Path, Path, Path]:
        source_manifest_path, source_manifest_hash = self._file_evidence("source-manifest.json")
        preservation_path, preservation_hash = self._file_evidence("source-preservation.log")
        rollback_path, rollback_hash = self._file_evidence("rollback-plan.json")
        migration = {
            "schema_version": "tool-defect-production-migration/v1",
            "migrator_version": "2.0.0",
            "migration_id": "migration-20260731-001",
            "execution_mode": "EXECUTE",
            "source_type": "REAL_PRODUCTION",
            "production_claim_allowed": True,
            "executor_id": "migration-operator-001",
            "started_at": "2026-07-31T01:00:00Z",
            "finished_at": "2026-07-31T01:10:00Z",
            "generated_at": "2026-07-31T01:10:01Z",
            "source_summary": {
                "overall_status": "COMPLETE",
                "production_claim_allowed": True,
                "manifests": {
                    "baseline-180": {
                        "status": "COMPLETE",
                        "file_errors": 0,
                        "cross_split_issues": 0,
                        "family_leak_issues": 0,
                        "label_consistency_issues": 0,
                    }
                },
            },
            "phases": {
                name: {"status": "PASSED", "details": {}, "errors": []}
                for name in REQUIRED_PHASES
            },
            "summary": {"overall_status": "COMPLETE"},
            "source_snapshot": {
                "snapshot_id": "snapshot-001",
                "manifest_path": source_manifest_path,
                "manifest_sha256": source_manifest_hash,
                "preservation_log_path": preservation_path,
                "preservation_log_sha256": preservation_hash,
                "source_deleted": False,
            },
            "rollback": {
                "scoped_to_migration_id": True,
                "source_preserved": True,
                "uses_unscoped_delete": False,
                "plan_path": rollback_path,
                "plan_sha256": rollback_hash,
            },
        }
        migration_path = self._write_json("production-migration-report.json", migration)

        postcheck_path, postcheck_hash = self._file_evidence("source-postcheck.log")
        verify_log_path, verify_log_hash = self._file_evidence("migration-verification.log")
        artifacts = {
            name: {
                "status": "PASS",
                "source_count": 1,
                "target_count": 1,
                "source_bytes": 64,
                "target_bytes": 64,
                "source_sha256": "a" * 64,
                "target_sha256": "a" * 64,
            }
            for name in REQUIRED_ARTIFACT_GROUPS
        }
        verification = {
            "schema_version": "tool-defect-production-migration-verification/v1",
            "overall_status": "PASS",
            "source_type": "REAL_PRODUCTION",
            "verification_scope": "FULL",
            "migration_id": "migration-20260731-001",
            "executor_id": "verification-operator-002",
            "started_at": "2026-07-31T01:11:00Z",
            "finished_at": "2026-07-31T01:20:00Z",
            "migration_report_path": str(migration_path.relative_to(self.root)),
            "migration_report_sha256": sha256_file(migration_path),
            "artifacts": artifacts,
            "categories": {
                "object_storage": {
                    "status": "PASS",
                    "expected_objects": 2,
                    "verified_objects": 2,
                    "missing_objects": 0,
                    "hash_mismatches": 0,
                    "expected_bytes": 128,
                    "verified_bytes": 128,
                }
            },
            "source_preservation": {
                "status": "PASS",
                "source_read_only": True,
                "source_deleted": False,
                "postcheck_path": postcheck_path,
                "postcheck_sha256": postcheck_hash,
            },
            "raw_log_path": verify_log_path,
            "raw_log_sha256": verify_log_hash,
        }
        verification_path = self._write_json("production-migration-verification.json", verification)

        recovery_log_path, recovery_log_hash = self._file_evidence("recovery.log")
        recovery = {
            "schema_version": "tool-defect-production-recovery/v1",
            "drill_id": "recovery-20260731-001",
            "source_type": "REAL_PRODUCTION",
            "environment": "ISOLATED_PRODUCTION_EQUIVALENT",
            "executor_id": "recovery-operator-003",
            "started_at": "2026-07-31T02:00:00Z",
            "finished_at": "2026-07-31T02:20:00Z",
            "result": "SUCCEEDED",
            "production_attestation_complete": True,
            "exact_scenario_set": True,
            "scenarios": [
                {"scenario": name, "passed": True}
                for name in REQUIRED_RECOVERY_SCENARIOS
            ],
            "rpo_target_seconds": 3600,
            "rpo_actual_seconds": 120,
            "rto_target_seconds": 1800,
            "rto_actual_seconds": 1200,
            "migration_verification_path": str(verification_path.relative_to(self.root)),
            "migration_verification_sha256": sha256_file(verification_path),
            "raw_log_path": recovery_log_path,
            "raw_log_sha256": recovery_log_hash,
            "sign_off": {
                "decision": "APPROVED",
                "signed_by": "recovery-approver-004",
                "signed_at": "2026-07-31T02:30:00Z",
                "reason": "全量恢复证据复核完成",
            },
        }
        recovery_path = self._write_json("recovery-drill-record.json", recovery)
        return migration_path, verification_path, recovery_path

    def test_missing_evidence_is_blocked_not_error(self):
        result = validate_p7_03_evidence(repo_root=self.root)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.errors, [])

    def test_complete_bound_evidence_passes(self):
        self._valid_reports()
        result = validate_p7_03_evidence(repo_root=self.root)
        self.assertEqual(result.status, "PASS", result.as_dict())

    def test_dry_run_migration_cannot_pass(self):
        migration_path, _, _ = self._valid_reports()
        report = json.loads(migration_path.read_text(encoding="utf-8"))
        report["execution_mode"] = "DRY_RUN"
        self._write_json(migration_path.name, report)
        result = validate_migration_report(repo_root=self.root, report_path=migration_path)
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("migration_execution_mode_invalid:DRY_RUN", result.blockers)

    def test_sampled_verification_cannot_pass(self):
        migration_path, verification_path, _ = self._valid_reports()
        report = json.loads(verification_path.read_text(encoding="utf-8"))
        report["verification_scope"] = "SAMPLED"
        self._write_json(verification_path.name, report)
        result = validate_migration_verification(
            repo_root=self.root,
            report_path=verification_path,
            migration_report_path=migration_path,
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("migration_verification_scope_not_full", result.blockers)

    def test_incomplete_recovery_scenarios_cannot_pass(self):
        _, verification_path, recovery_path = self._valid_reports()
        report = json.loads(recovery_path.read_text(encoding="utf-8"))
        report["scenarios"] = [{"scenario": "snapshot_backup", "passed": True}]
        self._write_json(recovery_path.name, report)
        result = validate_recovery_report(
            repo_root=self.root,
            report_path=recovery_path,
            verification_report_path=verification_path,
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("recovery_scenario_set_invalid", result.blockers)


if __name__ == "__main__":
    unittest.main()
