"""P7-07 与 G7 发布证据严格验证测试。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.p7.common import sha256_file
from tools.p7.release import (
    REQUIRED_G7_REQUIREMENTS,
    REQUIRED_RELEASE_SIGNOFFS,
    REQUIRED_TASKS,
    validate_final_release_decision,
    validate_g7_record,
    validate_p7_07_evidence,
    validate_repository_release_state,
)


class P7ReleaseValidationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.reports = self.root / "Docs/reports"
        self.evidence = self.root / "deploy/environments/production/evidence"
        self.reports.mkdir(parents=True)
        self.evidence.mkdir(parents=True)
        self._write_repository_state()

    def tearDown(self):
        self._temp.cleanup()

    def _write_json(self, path: Path, payload: dict) -> Path:
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return path

    def _evidence_file(self, name: str, content: str = "signed production evidence\n") -> tuple[str, str]:
        path = self.evidence / name
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.root)), sha256_file(path)

    def _write_repository_state(self, *, decision: str = "NO_GO", status: str = "BLOCKED") -> None:
        self._write_json(
            self.reports / "P7-go-live-checklist.json",
            {
                "schema_version": "tool-defect-go-live-checklist/v1",
                "sections": [
                    {"id": "SEC-01", "items": [{"id": "GL-001", "status": "PENDING_SITE_SIGNOFF"}]}
                ],
            },
        )
        self._write_json(
            self.reports / "P7-release-decision-record.json",
            {
                "schema_version": "tool-defect-release-decision-record/v1",
                "decision": decision,
                "status": status,
            },
        )

    def _signoffs(self) -> list[dict]:
        return [
            {
                "role": role,
                "decision": "APPROVED",
                "actor_id": f"signer-{role.lower()}",
                "signed_at": "2026-07-31T08:00:00Z",
                "reason": "所有真实生产证据已独立复核",
            }
            for role in REQUIRED_RELEASE_SIGNOFFS
        ]

    def _build_release_evidence(self) -> tuple[Path, Path, str, str]:
        evidence_path, evidence_hash = self._evidence_file("release-evidence.log")
        checklist = {
            "schema_version": "tool-defect-go-live-checklist/v2",
            "status": "PASS",
            "source_type": "REAL_PRODUCTION",
            "contract_version": "v1",
            "release_id": "release-001",
            "generated_at": "2026-07-31T07:00:00Z",
            "summary": {
                "total_items": 2,
                "pass": 1,
                "not_applicable": 1,
                "pending": 0,
                "high_risk_items": 0,
            },
            "sections": [
                {
                    "id": "SEC-01",
                    "items": [
                        {
                            "id": "GL-001",
                            "status": "PASS",
                            "risk": "LOW",
                            "evidence": [{"path": evidence_path, "sha256": evidence_hash}],
                        },
                        {
                            "id": "GL-002",
                            "status": "NOT_APPLICABLE",
                            "risk": "LOW",
                            "waiver": {
                                "status": "APPROVED",
                                "owner_id": "waiver-owner",
                                "approver_id": "waiver-approver",
                                "compensating_control": "保留监控并在条件变化时重新评审",
                                "reason": "首期范围明确不适用",
                                "expires_at": "2027-07-31T00:00:00Z",
                                "approved_at": "2026-07-31T06:00:00Z",
                            },
                        },
                    ],
                }
            ],
        }
        checklist_path = self._write_json(self.evidence / "go-live-checklist.json", checklist)
        decision = {
            "schema_version": "tool-defect-release-decision-record/v2",
            "status": "APPROVED",
            "decision": "GO",
            "source_type": "REAL_PRODUCTION",
            "contract_version": "v1",
            "release_id": "release-001",
            "release_version": "R8",
            "current_model_version_id": "model-current-001",
            "decided_at": "2026-07-31T08:00:00Z",
            "release_at": "2026-08-01T00:00:00Z",
            "conditions_met": True,
            "checklist_path": str(checklist_path.relative_to(self.root)),
            "checklist_sha256": sha256_file(checklist_path),
            "task_results": {
                f"P7-{number:02d}": {
                    "status": "PASS",
                    "evidence_path": evidence_path,
                    "evidence_sha256": evidence_hash,
                }
                for number in range(1, 7)
            },
            "risk_register": [
                {
                    "id": "RISK-001",
                    "severity": "HIGH",
                    "status": "CLOSED",
                    "resolution": "真实节拍验收已通过",
                    "closed_at": "2026-07-31T07:30:00Z",
                }
            ],
            "rollback_target": {
                "model_version_id": "model-stable-previous-001",
                "package_sha256": "a" * 64,
                "registry_alias": "stable-previous",
                "signature_verified": True,
                "warmed": True,
                "health_ready": True,
                "rollback_exercised": True,
                "evidence_path": evidence_path,
                "evidence_sha256": evidence_hash,
            },
            "duty_roster": {
                "status": "ACTIVE",
                "starts_at": "2026-08-01T00:00:00Z",
                "ends_at": "2026-08-08T00:00:00Z",
                "coverage_complete": True,
                "uncovered_seconds": 0,
                "slots": [
                    {
                        "operations_actor_id": "ops-on-call",
                        "quality_actor_id": "quality-on-call",
                        "algorithm_actor_id": "algorithm-on-call",
                    }
                ],
                "evidence_path": evidence_path,
                "evidence_sha256": evidence_hash,
            },
            "sign_offs": self._signoffs(),
            "raw_log_path": evidence_path,
            "raw_log_sha256": evidence_hash,
        }
        decision_path = self._write_json(self.evidence / "release-decision-record.json", decision)
        return checklist_path, decision_path, evidence_path, evidence_hash

    def _build_g7(self, evidence_path: str, evidence_hash: str) -> Path:
        report = {
            "schema_version": "tool-defect-p7-gate-acceptance/v1",
            "gate_id": "g7-release-001",
            "release_id": "release-001",
            "contract_version": "v1",
            "source_type": "REAL_PRODUCTION",
            "generated_at": "2026-07-31T09:00:00Z",
            "status": "PASS",
            "production_claim_allowed": True,
            "task_results": [
                {
                    "task_id": task_id,
                    "status": "PASS",
                    "evidence_path": evidence_path,
                    "evidence_sha256": evidence_hash,
                }
                for task_id in REQUIRED_TASKS
            ],
            "requirements": {
                name: {
                    "status": "PASS",
                    "evidence_path": evidence_path,
                    "evidence_sha256": evidence_hash,
                }
                for name in REQUIRED_G7_REQUIREMENTS
            },
            "sign_offs": self._signoffs(),
            "raw_log_path": evidence_path,
            "raw_log_sha256": evidence_hash,
        }
        return self._write_json(self.reports / "P7-gate-acceptance.json", report)

    def test_repository_state_rejects_conditional_go(self):
        self._write_repository_state(decision="CONDITIONAL_GO", status="PENDING")
        result = validate_repository_release_state(repo_root=self.root)
        self.assertEqual(result.status, "ERROR")
        self.assertIn("repository_conditional_go_forbidden", result.errors)

    def test_complete_release_evidence_passes(self):
        self._build_release_evidence()
        result = validate_p7_07_evidence(repo_root=self.root)
        self.assertEqual(result.status, "PASS", result.as_dict())

    def test_open_high_risk_blocks_go(self):
        checklist_path, decision_path, _, _ = self._build_release_evidence()
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        decision["risk_register"][0]["status"] = "OPEN"
        self._write_json(decision_path, decision)
        result = validate_final_release_decision(
            repo_root=self.root,
            decision_path=decision_path,
            checklist_path=checklist_path,
        )
        self.assertIn("release_risk_not_closed:RISK-001:OPEN", result.blockers)

    def test_incomplete_duty_roster_blocks_go(self):
        checklist_path, decision_path, _, _ = self._build_release_evidence()
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        decision["duty_roster"]["ends_at"] = "2026-08-07T23:59:59Z"
        decision["duty_roster"]["coverage_complete"] = False
        decision["duty_roster"]["uncovered_seconds"] = 1
        self._write_json(decision_path, decision)
        result = validate_final_release_decision(
            repo_root=self.root,
            decision_path=decision_path,
            checklist_path=checklist_path,
        )
        self.assertIn("release_duty_roster_window_insufficient", result.blockers)
        self.assertIn("release_duty_roster_coverage_incomplete", result.blockers)

    def test_complete_g7_record_passes(self):
        _, _, evidence_path, evidence_hash = self._build_release_evidence()
        gate_path = self._build_g7(evidence_path, evidence_hash)
        result = validate_g7_record(repo_root=self.root, report_path=gate_path)
        self.assertEqual(result.status, "PASS", result.as_dict())

    def test_blocked_task_blocks_g7(self):
        _, _, evidence_path, evidence_hash = self._build_release_evidence()
        gate_path = self._build_g7(evidence_path, evidence_hash)
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        gate["task_results"][0]["status"] = "BLOCKED"
        self._write_json(gate_path, gate)
        result = validate_g7_record(repo_root=self.root, report_path=gate_path)
        self.assertTrue(any(message.startswith("g7_task_not_pass:") for message in result.blockers))


if __name__ == "__main__":
    unittest.main()
