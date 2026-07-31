"""P7-06 用户、运维和应急演练严格证据测试。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.p7.common import sha256_file
from tools.p7.operations import (
    HIGH_RISK_SCENARIOS,
    REQUIRED_CONTACT_ROLES,
    REQUIRED_MANUALS,
    REQUIRED_P7_SCENARIOS,
    REQUIRED_SIGNOFF_ROLES,
    validate_emergency_contacts,
    validate_p7_06_evidence,
)


class P7OperationsValidationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.runbooks = self.root / "Docs/runbooks"
        self.evidence = self.root / "deploy/environments/production/evidence"
        self.runbooks.mkdir(parents=True)
        self.evidence.mkdir(parents=True)

    def tearDown(self):
        self._temp.cleanup()

    def _file(self, path: Path, content: str) -> tuple[str, str]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.root)), sha256_file(path)

    def _write_json(self, path: Path, payload: dict) -> Path:
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return path

    def _build_catalog_and_manuals(self) -> list[str]:
        manual_body = (
            "# 角色手册\n\n所需权限、操作原因、二次确认、审计事件均必须记录。"
            "禁止越权；未知状态保持 HOLD。\n"
        )
        for filename in REQUIRED_MANUALS.values():
            self._file(self.runbooks / filename, manual_body)
        self._file(self.runbooks / "README.md", "# 手册索引\n")
        scenarios = [
            {
                "id": f"DRILL-{index:02d}",
                "severity": "S2",
                "title": f"基础场景 {index}",
                "trigger": "真实触发",
                "expected_system_behavior": "安全失败并恢复",
                "recovery_steps": ["确认", "恢复"],
                "success_criteria": ["无丢失", "审计完整"],
                "runbook_ref": "README.md",
                "required_participants": ["运维", "审计"],
            }
            for index in range(1, 15)
        ]
        for scenario_id, scenario_type in REQUIRED_P7_SCENARIOS.items():
            scenarios.append(
                {
                    "id": scenario_id,
                    "scenario_type": scenario_type,
                    "severity": "S1",
                    "title": scenario_type,
                    "trigger": "真实生产设备受控触发",
                    "expected_system_behavior": "未知状态进入 HOLD 并记录审计",
                    "recovery_steps": ["确认影响", "恢复并复核"],
                    "success_criteria": ["无错误 PASS", "审计完整"],
                    "runbook_ref": "README.md",
                    "required_participants": ["外部用户", "审计员"],
                    "requires_reason": True,
                    "requires_second_confirmation": True,
                    "requires_audit": True,
                }
            )
        self._write_json(
            self.runbooks / "emergency-drill-scenarios.json",
            {
                "schema_version": "tool-defect-emergency-drill/v1",
                "drill_environment": "REAL_PRODUCTION_EQUIPMENT",
                "scenarios": scenarios,
            },
        )
        return [item["id"] for item in scenarios]

    def _build_contacts(self) -> Path:
        roster_path, roster_hash = self._file(self.evidence / "duty-roster.csv", "role,actor\n")
        contacts = {
            "schema_version": "tool-defect-emergency-contacts/v1",
            "status": "ACTIVE",
            "source_type": "REAL_PRODUCTION",
            "verified_at": "2026-07-31T01:00:00Z",
            "communication_channels": {
                name: {"status": "ACTIVE", "type": f"channel-{name}", "details": f"route-{name}"}
                for name in ("primary", "backup")
            },
            "roles": {
                role: {
                    "actor_id": f"actor-{role}",
                    "name": f"person-{role}",
                    "phone": f"phone-{role}",
                    "email": f"{role}@factory.invalid",
                    "on_call": True,
                    "verified_at": "2026-07-31T01:00:00Z",
                }
                for role in REQUIRED_CONTACT_ROLES
            },
            "duty_roster_path": roster_path,
            "duty_roster_sha256": roster_hash,
        }
        return self._write_json(self.evidence / "emergency-contacts.json", contacts)

    def _build_drill(self, scenario_ids: list[str], contacts_path: Path) -> Path:
        drill_log_path, drill_log_hash = self._file(self.evidence / "operations-drill.log", "field drill\n")
        scenario_results = []
        for scenario_id in scenario_ids:
            item = {
                "scenario_id": scenario_id,
                "status": "PASS",
                "executed_by": "operator-external",
                "started_at": "2026-07-31T02:00:00Z",
                "finished_at": "2026-07-31T02:10:00Z",
                "actual_behavior": "真实设备行为与预期一致",
                "recovery_time_seconds": 600,
                "hold_on_unknown": True,
                "role_separation_verified": True,
                "evidence_path": drill_log_path,
                "evidence_sha256": drill_log_hash,
            }
            if scenario_id in HIGH_RISK_SCENARIOS:
                item.update(
                    {
                        "reason": "受控应急演练",
                        "confirmed_by": "independent-confirmer",
                        "audit_event_id": f"audit-{scenario_id}",
                        "audit_verified": True,
                    }
                )
            if scenario_id == "DRILL-15":
                item.update({"normal_workflow_complete": True, "traceability_complete": True})
            elif scenario_id == "DRILL-16":
                item.update({"all_unauthorized_requests_denied": True, "state_changes": 0})
            elif scenario_id == "DRILL-17":
                item.update({"blind_bulk_replay": False, "unreconciled_duplicates": 0, "unrecoverable_state": "HOLD"})
            elif scenario_id == "DRILL-18":
                item.update({"stable_previous_warmed": True, "history_unchanged": True, "rollback_completed": True})
            elif scenario_id == "DRILL-19":
                item.update({"revoked_certificate_denied": True, "device_state": "HOLD"})
            elif scenario_id == "DRILL-20":
                item.update({"dual_approval": True, "least_privilege": True, "account_disabled_after": True, "credentials_rotated": True})
            scenario_results.append(item)
        report = {
            "schema_version": "tool-defect-p7-user-operations-drill/v1",
            "status": "PASS",
            "source_type": "REAL_PRODUCTION_EQUIPMENT",
            "environment": "production",
            "development_team_executed": False,
            "drill_id": "operations-drill-001",
            "coordinator_id": "coordinator-external",
            "started_at": "2026-07-31T02:00:00Z",
            "finished_at": "2026-07-31T05:00:00Z",
            "participants": [
                {
                    "role": role,
                    "actor_id": f"external-{role.lower()}",
                    "external_user": True,
                    "involved_in_development": False,
                    "training_completed": True,
                    "training_completed_at": "2026-07-30T01:00:00Z",
                }
                for role in REQUIRED_MANUALS
            ],
            "scenario_results": scenario_results,
            "contacts_path": str(contacts_path.relative_to(self.root)),
            "contacts_sha256": sha256_file(contacts_path),
            "raw_log_path": drill_log_path,
            "raw_log_sha256": drill_log_hash,
            "sign_offs": [
                {
                    "role": role,
                    "decision": "APPROVED",
                    "actor_id": f"signer-{role.lower()}",
                    "signed_at": "2026-07-31T06:00:00Z",
                    "reason": "外部用户真实设备演练复核完成",
                }
                for role in REQUIRED_SIGNOFF_ROLES
            ],
        }
        return self._write_json(self.evidence / "user-operations-drill.json", report)

    def _build_all(self) -> tuple[list[str], Path, Path]:
        scenario_ids = self._build_catalog_and_manuals()
        contacts_path = self._build_contacts()
        drill_path = self._build_drill(scenario_ids, contacts_path)
        return scenario_ids, contacts_path, drill_path

    def test_complete_external_user_drill_passes(self):
        self._build_all()
        result = validate_p7_06_evidence(repo_root=self.root)
        self.assertEqual(result.status, "PASS", result.as_dict())

    def test_developer_participant_is_blocked(self):
        _, _, drill_path = self._build_all()
        report = json.loads(drill_path.read_text(encoding="utf-8"))
        report["participants"][0]["involved_in_development"] = True
        self._write_json(drill_path, report)
        result = validate_p7_06_evidence(repo_root=self.root)
        self.assertIn("drill:operations_drill_participant_not_external:OPERATOR", result.blockers)

    def test_missing_permission_scenario_is_blocked(self):
        _, _, drill_path = self._build_all()
        report = json.loads(drill_path.read_text(encoding="utf-8"))
        report["scenario_results"] = [
            item for item in report["scenario_results"] if item["scenario_id"] != "DRILL-16"
        ]
        self._write_json(drill_path, report)
        result = validate_p7_06_evidence(repo_root=self.root)
        self.assertIn("drill:operations_drill_scenario_coverage_invalid", result.blockers)

    def test_pending_contacts_are_blocked(self):
        _, contacts_path, _ = self._build_all()
        contacts = json.loads(contacts_path.read_text(encoding="utf-8"))
        contacts["status"] = "PENDING_SITE_FILL"
        self._write_json(contacts_path, contacts)
        result = validate_emergency_contacts(repo_root=self.root, contacts_path=contacts_path)
        self.assertEqual(result.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
