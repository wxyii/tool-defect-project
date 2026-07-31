from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.p7.common import ValidationResult, read_simple_yaml_mapping
from tools.p7.preflight import (
    REQUIRED_IMAGE_NAMES,
    TECHNOLOGY_DECISION_IDS,
    validate_config,
    validate_env,
    validate_preflight_results,
    validate_smoke_evidence,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _yaml_scalar(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _dump_yaml(value: dict[str, object], indent: int = 0) -> str:
    lines: list[str] = []
    for key, child in value.items():
        prefix = " " * indent + f"{key}:"
        if isinstance(child, dict):
            lines.append(prefix)
            lines.append(_dump_yaml(child, indent + 2))
        else:
            lines.append(f"{prefix} {_yaml_scalar(child)}")
    return "\n".join(lines)


class P7YamlSubsetTests(unittest.TestCase):
    def test_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "site.yaml"
            path.write_text("storage:\n  protocol: S3_COMPATIBLE\n  protocol: S3\n", encoding="utf-8")
            result = ValidationResult("test")
            self.assertEqual({}, read_simple_yaml_mapping(path, result, "site"))
            self.assertEqual("ERROR", result.status)
            self.assertTrue(any("重复键" in item for item in result.errors))


class P7ProductionConfigTests(unittest.TestCase):
    def _create_valid_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        registry = json.loads(
            (PROJECT_ROOT / "Docs/decisions/site-parameter-decisions.json").read_text(
                encoding="utf-8"
            )
        )
        registry_path = root / "registry.json"
        _write_json(registry_path, registry)

        evidence = root / "site-approval.txt"
        evidence.write_text("真实现场审批证据固定内容", encoding="utf-8")
        evidence_hash = _sha256(evidence)
        approval = {
            "approver_id": "site-owner-001",
            "role": "现场负责人",
            "approved_at": "2026-07-31T10:00:00+08:00",
            "evidence_path": evidence.name,
            "evidence_sha256": evidence_hash,
        }
        closure_items = [
            {
                "id": decision["id"],
                "title": decision["title"],
                "closure_status": "CONFIRMED",
                "closure_evidence": "现场签署记录",
                "residual_risk": "已登记",
                "approval": dict(approval),
            }
            for decision in registry["decisions"]
        ]
        closure_path = root / "closure.json"
        _write_json(
            closure_path,
            {
                "schema_version": "1.0.0",
                "closure_date": "2026-07-31T10:00:00+08:00",
                "closure_authority": "现场上线评审组",
                "summary": {
                    "total_decisions": len(closure_items),
                    "pending_site_signoff": 0,
                    "confirmed": len(closure_items),
                    "confirmed_default": 0,
                    "deferred": 0,
                },
                "decisions": closure_items,
            },
        )

        site_config = {
            "schema_version": "1.0.0",
            "site_config_version": "site-v1",
            "deployed_at": "2026-07-31T10:00:00+08:00",
            "capture": {
                "plc_protocol": "modbus_tcp",
                "trigger_mode": "PLC",
                "camera_model": "camera-model-v1",
                "camera_sdk": "camera-sdk-1.2.3",
                "real_hardware_enabled": True,
                "edge_operating_system": "edge-os-1.2.3",
            },
            "performance": {
                "cycle_time_ms": 500,
                "allowed_latency_ms": 200,
                "slo_claims_enabled": True,
            },
            "offline": {
                "maximum_offline_hours": 8,
                "delete_unsynchronized_images": False,
            },
            "capacity": {
                "local_disk_capacity_gb": 512,
                "disk_warning_percent": 80,
                "disk_critical_percent": 90,
                "disk_pause_percent": 95,
            },
            "disposition": {
                "automatic_pass_enabled": False,
                "qualification_threshold": 0.95,
                "unqualification_threshold": 0.4,
                "unknown_threshold_action": "HOLD",
                "technical_failure_action": "HOLD",
                "sampling_ratio": 0.1,
            },
            "review": {"sla_minutes": 30, "overdue_action": "ESCALATE_AND_HOLD"},
            "retention": {
                "raw_image_days": 365,
                "review_record_days": 730,
                "training_data_days": 365,
                "automatic_deletion_enabled": False,
                "derived_image_days": 180,
            },
            "recovery": {
                "rpo_minutes": 15,
                "rto_minutes": 60,
                "high_availability_enabled": True,
                "restore_target_confirmed": True,
            },
            "identity": {
                "provider": "enterprise-idp-1.2.3",
                "production_authentication_enabled": True,
            },
            "storage": {
                "protocol": "S3_COMPATIBLE",
                "public_access_enabled": False,
                "product": "object-store-1.2.3",
                "endpoint": "https://object-storage.internal",
                "signed_url_ttl_seconds": 300,
            },
            "messaging": {"product": "queue-1.2.3", "high_availability_enabled": True},
            "monitoring": {"platform": "monitor-1.2.3", "production_alerting_enabled": True},
            "compute": {"inference_device": "cpu-v1", "server_operating_system": "server-os-1.2.3"},
            "deployment": {"platform": "compose-2.3.4", "kubernetes_enabled": False},
        }
        config_path = root / "site-config.yaml"
        config_path.write_text(_dump_yaml(site_config) + "\n", encoding="utf-8")

        sbom = root / "component-sbom.json"
        _write_json(sbom, {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [{"name": "component", "version": "1.2.3"}]})
        license_evidence = root / "license-review.txt"
        license_evidence.write_text("许可证审查已批准", encoding="utf-8")
        inventory_path = root / "technology-inventory.json"
        _write_json(
            inventory_path,
            {
                "schema_version": "tool-defect-technology-inventory/v1",
                "status": "APPROVED",
                "source_type": "REAL_SITE",
                "generated_at": "2026-07-31T10:00:00+08:00",
                "items": [
                    {
                        "id": identifier,
                        "component": identifier.lower(),
                        "product": "approved-product",
                        "exact_version": "1.2.3",
                        "license": "approved-license",
                        "support_end": "2030-12-31",
                        "artifact_sha256": "a" * 64,
                        "sbom_path": sbom.name,
                        "sbom_sha256": _sha256(sbom),
                        "license_evidence_path": license_evidence.name,
                        "license_evidence_sha256": _sha256(license_evidence),
                        "approval": dict(approval),
                    }
                    for identifier in sorted(TECHNOLOGY_DECISION_IDS)
                ],
            },
        )
        return registry_path, closure_path, config_path, inventory_path

    def test_current_template_is_blocked_not_error(self) -> None:
        result = validate_config(repo_root=PROJECT_ROOT)
        self.assertEqual("BLOCKED", result.status)
        self.assertEqual(2, result.exit_code)
        self.assertGreater(len(result.blockers), 10)
        self.assertEqual([], result.errors)

    def test_complete_real_fixture_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry, closure, config, inventory = self._create_valid_fixture(root)
            result = validate_config(
                repo_root=root,
                registry_path=registry,
                closure_path=closure,
                site_config_path=config,
                inventory_path=inventory,
            )
            self.assertEqual(result.as_dict(), result.as_dict())
            self.assertEqual("PASS", result.status, result.as_dict())


class P7ProductionEnvironmentTests(unittest.TestCase):
    def test_valid_digest_locked_environment_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            lines = [
                "TD_RELEASE_ID=release-20260731-001",
                "TD_ENVIRONMENT=production",
                "COMPOSE_PROJECT_NAME=tool-defect-production",
            ]
            for image in REQUIRED_IMAGE_NAMES:
                lines.append(f"TD_{image}_IMAGE_REPOSITORY=registry.local/{image.lower()}")
                lines.append(f"TD_{image}_IMAGE_DIGEST={'a' * 64}")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = validate_env(repo_root=Path(temporary), env_path=path)
            self.assertEqual("PASS", result.status, result.as_dict())

    def test_plaintext_secret_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            lines = [
                "TD_RELEASE_ID=release-1",
                "TD_ENVIRONMENT=production",
                "COMPOSE_PROJECT_NAME=tool-defect-production",
                "DATABASE_PASSWORD=unsafe-value",
            ]
            for image in REQUIRED_IMAGE_NAMES:
                lines.append(f"TD_{image}_IMAGE_REPOSITORY=registry.local/{image.lower()}")
                lines.append(f"TD_{image}_IMAGE_DIGEST={'b' * 64}")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            result = validate_env(repo_root=Path(temporary), env_path=path)
            self.assertEqual("ERROR", result.status)
            self.assertIn("plaintext_secret_forbidden:DATABASE_PASSWORD", result.errors)


class P7StructuredEvidenceTests(unittest.TestCase):
    def test_preflight_requires_hashed_real_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "command.log"
            evidence.write_text("command passed", encoding="utf-8")
            checklist = root / "checklist.json"
            results = root / "results.json"
            command = "verify-static-control --strict"
            _write_json(
                checklist,
                {
                    "schema_version": "1.0.0",
                    "items": [
                        {
                            "id": "CFG-001",
                            "required": True,
                            "verification_command": command,
                            "expected_result": "PASS",
                        }
                    ],
                },
            )
            _write_json(
                results,
                {
                    "schema_version": "tool-defect-preflight-results/v1",
                    "status": "PASS",
                    "source_type": "REAL_SITE",
                    "environment": "production",
                    "started_at": "2026-07-31T10:00:00+08:00",
                    "finished_at": "2026-07-31T10:01:00+08:00",
                    "executor_id": "operator-001",
                    "host_id": "production-host-001",
                    "site_config_sha256": "c" * 64,
                    "release_id": "release-001",
                    "items": [
                        {
                            "id": "CFG-001",
                            "status": "PASS",
                            "exit_code": 0,
                            "command_template": command,
                            "verification_command": command,
                            "executed_at": "2026-07-31T10:00:30+08:00",
                            "executor_id": "operator-001",
                            "host_id": "production-host-001",
                            "actual_result": "PASS",
                            "evidence_path": evidence.name,
                            "evidence_sha256": _sha256(evidence),
                        }
                    ],
                },
            )
            result = validate_preflight_results(
                repo_root=root,
                checklist_path=checklist,
                results_path=results,
            )
            self.assertEqual("PASS", result.status, result.as_dict())

    def test_smoke_evidence_rejects_simulation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "smoke.json"
            _write_json(
                evidence,
                {
                    "schema_version": "tool-defect-model-smoke/v1",
                    "status": "PASS",
                    "source_type": "SIMULATION",
                    "environment": "production",
                },
            )
            result = validate_smoke_evidence(repo_root=root, evidence_path=evidence)
            self.assertEqual("BLOCKED", result.status)
            self.assertIn("model_smoke_not_real_infrastructure", result.blockers)


if __name__ == "__main__":
    unittest.main()
