"""P7-04 非功能现场证据严格验证测试。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.p7.common import sha256_file
from tools.p7.nonfunctional import (
    REQUIRED_FAULT_SCENARIOS,
    REQUIRED_SECURITY_CONTROLS,
    REQUIRED_SIGNOFF_ROLES,
    REQUIRED_TEST_RUNS,
    REQUIRED_THRESHOLDS,
    validate_nonfunctional_report,
)


class P7NonfunctionalValidationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.evidence = self.root / "deploy/environments/production/evidence"
        self.evidence.mkdir(parents=True)

    def tearDown(self):
        self._temp.cleanup()

    def _evidence_file(self, name: str, content: str = "real field evidence\n") -> tuple[str, str]:
        path = self.evidence / name
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.root)), sha256_file(path)

    def _valid_report(self) -> dict:
        config_path, config_hash = self._evidence_file("site-config.yaml", "site: approved\n")
        approval_path, approval_hash = self._evidence_file("threshold-approval.json", "{}")
        log_path, log_hash = self._evidence_file("field-run.log")
        thresholds = {
            name: {
                "value": {
                    "cycle_time_ms": 200,
                    "allowed_latency_ms": 150,
                    "sustained_duration_seconds": 3600,
                    "max_offline_hours": 8,
                    "rpo_seconds": 300,
                    "rto_seconds": 600,
                    "concurrent_reviews": 5,
                    "capacity_bytes": 1000,
                }[name],
                "status": "CONFIRMED",
                "decision_id": f"decision-{name}",
                "approved_by": "site-approver-001",
                "approved_at": "2026-07-31T01:00:00Z",
            }
            for name in REQUIRED_THRESHOLDS
        }
        return {
            "schema_version": "tool-defect-non-functional-acceptance/v1",
            "status": "PASS",
            "source_type": "REAL_PRODUCTION",
            "environment": "production",
            "contract_version": "v1",
            "run_id": "nfa-run-001",
            "executor_id": "nfa-executor-001",
            "host_id": "production-host-001",
            "started_at": "2026-07-31T02:00:00Z",
            "finished_at": "2026-07-31T04:00:00Z",
            "site_config_path": config_path,
            "site_config_sha256": config_hash,
            "threshold_approval_path": approval_path,
            "threshold_approval_sha256": approval_hash,
            "test_runs": {
                name: {
                    "command": command,
                    "status": "PASS",
                    "exit_code": 0,
                    "skipped": 0,
                    "total": 10,
                    "simulator_only": False,
                    "source_type": "REAL_PRODUCTION",
                    "raw_log_path": log_path,
                    "raw_log_sha256": log_hash,
                }
                for name, command in REQUIRED_TEST_RUNS.items()
            },
            "signed_thresholds": thresholds,
            "performance": {
                "end_to_end_p95_ms": 100,
                "cycle_margin_ms": 100,
                "throughput_per_second": 10,
                "sustained_duration_seconds": 3600,
                "concurrent_reviews": 5,
                "capacity_bytes_tested": 1000,
                "failures": 0,
                "original_images_lost": 0,
                "rpo_actual_seconds": 120,
                "rto_actual_seconds": 300,
            },
            "fault_scenarios": [
                {
                    "name": name,
                    "status": "PASS",
                    "real_fault_injection": True,
                    "critical_data_loss": 0,
                    "unreconciled_duplicates": 0,
                    "hold_on_unknown": True,
                    "evidence_path": log_path,
                    "evidence_sha256": log_hash,
                }
                for name in REQUIRED_FAULT_SCENARIOS
            ],
            "security_controls": [
                {
                    "name": name,
                    "status": "PASS",
                    "real_probe": True,
                    "critical_findings": 0,
                    "evidence_path": log_path,
                    "evidence_sha256": log_hash,
                }
                for name in REQUIRED_SECURITY_CONTROLS
            ],
            "critical_alerts": [
                {"alert_id": "alert-storage-down", "triggered": True, "recovered": True}
            ],
            "sign_offs": [
                {
                    "role": role,
                    "decision": "APPROVED",
                    "actor_id": f"{role.lower()}-approver",
                    "signed_at": "2026-07-31T05:00:00Z",
                    "reason": "真实现场非功能证据复核完成",
                }
                for role in REQUIRED_SIGNOFF_ROLES
            ],
        }

    def _write(self, report: dict) -> Path:
        path = self.evidence / "non-functional-acceptance.json"
        path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        return path

    def test_missing_report_is_blocked(self):
        result = validate_nonfunctional_report(repo_root=self.root)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.errors, [])

    def test_complete_real_report_passes(self):
        path = self._write(self._valid_report())
        result = validate_nonfunctional_report(repo_root=self.root, report_path=path)
        self.assertEqual(result.status, "PASS", result.as_dict())

    def test_simulator_only_run_is_blocked(self):
        report = self._valid_report()
        report["test_runs"]["faults"]["simulator_only"] = True
        path = self._write(report)
        result = validate_nonfunctional_report(repo_root=self.root, report_path=path)
        self.assertIn("nonfunctional_test_simulator_only_not_false:faults", result.blockers)

    def test_pending_threshold_is_blocked(self):
        report = self._valid_report()
        report["signed_thresholds"]["cycle_time_ms"]["status"] = "PENDING_SITE_SIGNOFF"
        path = self._write(report)
        result = validate_nonfunctional_report(repo_root=self.root, report_path=path)
        self.assertIn("nonfunctional_threshold_not_confirmed:cycle_time_ms", result.blockers)


if __name__ == "__main__":
    unittest.main()
