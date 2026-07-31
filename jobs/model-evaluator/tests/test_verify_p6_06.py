import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "verify_p6_06", ROOT / "jobs/model-evaluator/verify_p6_06.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


class DeploymentVerifierTests(unittest.TestCase):
    def _evidence(self, root: Path) -> Path:
        package = root / "deployment"
        package.mkdir()
        model_id = str(uuid.uuid4())
        previous_id = str(uuid.uuid4())
        model_hash = "a" * 64
        previous_hash = "b" * 64
        plan = {
            "schema_version": "p6-06-deployment-plan.v1",
            "status": "COMPLETE",
            "immutable": True,
            "p6_05_registry_status": "COMPLETE",
            "model_version_id": model_id,
            "package_sha256": model_hash,
            "rollback_model_version_id": previous_id,
            "rollback_package_sha256": previous_hash,
            "production_alias": "production",
            "stable_previous_alias": "stable-previous",
            "target_ref": {"model_version_id": model_id, "package_sha256": model_hash},
            "production_status": "ACTIVE",
            "activated_after_canary": True,
            "production_traffic_ratio": 1,
        }
        write_json(package / "deployment-plan.json", plan)
        write_json(
            package / "runtime-evidence.json",
            {
                "schema_version": "p6-06-runtime-evidence.v1",
                "status": "COMPLETE",
                "dual_slot": True,
                "slots": [
                    {"slot_id": "slot-new", "model_version_id": model_id, "package_sha256": model_hash, "state": "READY", "signature_status": "VERIFIED", "warmed": True, "health_ready": True, "isolated": True},
                    {"slot_id": "slot-old", "model_version_id": previous_id, "package_sha256": previous_hash, "state": "READY", "signature_status": "VERIFIED", "warmed": True, "health_ready": True, "isolated": True},
                ],
                "load_failure_cases": [{"traffic_enabled": False, "state": "HOLD", "result": "NO_RESULT"}],
            },
        )
        common = {
            "status": "COMPLETE",
            "model_version_id": model_id,
            "package_sha256": model_hash,
            "gate_state": "APPROVED",
            "observation_window_seconds": 3600,
            "minimum_sample_count": 100,
            "sample_count": 120,
            "metrics": {"error_rate": 0.0, "disagreement_rate": 0.01},
        }
        write_json(package / "shadow-report.json", {"schema_version": "p6-06-shadow-observation.v1", "traffic_ratio": 0, **common})
        write_json(package / "canary-report.json", {"schema_version": "p6-06-canary-observation.v1", "traffic_ratio": 0.1, "station_ids": [str(uuid.uuid4())], **common})
        write_json(
            package / "rollback-report.json",
            {
                "schema_version": "p6-06-rollback-evidence.v1",
                "status": "COMPLETE",
                "executed": True,
                "source_model_version_id": model_id,
                "source_package_sha256": model_hash,
                "target_model_version_id": previous_id,
                "target_package_sha256": previous_hash,
                "history_unchanged": True,
                "new_tasks_target_rollback": True,
                "existing_tasks_unchanged": True,
                "new_slot_drained": True,
                "evidence_preserved": True,
                "execution_mode": "PRODUCTION_EQUIVALENT",
                "reason": "固定探针回滚验证",
                "operator": "release-operator",
            },
        )
        events = []
        for index, state in enumerate(MODULE.REQUIRED_EVENT_STATES, start=1):
            event = {"event_id": f"event-{index}", "state": state, "actor_id": "operator", "at": f"2026-07-31T0{index}:00:00Z"}
            event["event_sha256"] = hashlib.sha256(MODULE.canonical_json(event)).hexdigest()
            events.append(event)
        write_json(package / "deployment-events.json", {"events": events})
        write_json(package / "report.json", {"schema_version": "p6-06-deployment-report.v1", "status": "COMPLETE", "immutable": True, "production_release_allowed": True, "model_version_id": model_id, "package_sha256": model_hash})
        return package

    def test_missing_deployment_evidence_is_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = MODULE.verify_package(Path(temporary))
        self.assertEqual(result["status"], "BLOCKED")

    def test_complete_dual_slot_evidence_passes_and_zero_canary_is_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = self._evidence(Path(temporary))
            result = MODULE.verify_package(package)
            self.assertEqual(result["status"], "COMPLETE", result)
            canary = json.loads((package / "canary-report.json").read_text(encoding="utf-8"))
            canary["traffic_ratio"] = 0
            write_json(package / "canary-report.json", canary)
            blocked = MODULE.verify_package(package)
            self.assertEqual(blocked["status"], "BLOCKED")
            self.assertIn("canary:traffic_ratio_must_be_between_zero_and_one", blocked["errors"])


if __name__ == "__main__":
    unittest.main()
