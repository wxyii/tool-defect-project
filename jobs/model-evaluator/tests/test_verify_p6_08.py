import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "verify_p6_08", ROOT / "jobs/model-evaluator/verify_p6_08.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
validate = MODULE.validate


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class P608EvidenceTests(unittest.TestCase):
    def test_in_memory_evidence_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in (
                "component-manifest.json",
                "lifecycle-report.json",
                "traceability.json",
                "runtime-evidence.json",
                "report.json",
            ):
                (root / filename).write_text("{}", encoding="utf-8")
            errors = validate(root)
            self.assertIn("report.execution_mode:must_be_nonempty_text", errors)

    def test_real_component_evidence_can_pass_local_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            components = []
            for name, endpoint in (
                ("business-api", "http://127.0.0.1:18080/actuator/health"),
                ("inference-service", "http://127.0.0.1:18081/health"),
                ("postgresql", "postgresql://127.0.0.1:15432"),
                ("object-storage", "http://127.0.0.1:19000/health"),
            ):
                probe_path = root / "probes" / f"{name}.json"
                probe_path.parent.mkdir(parents=True, exist_ok=True)
                write_json(
                    probe_path,
                    {
                        "component": name,
                        "status": "PASS",
                        "request_id": f"probe-{name}",
                        "observed_at": "2026-07-31T00:00:00Z",
                        "response_sha256": "a" * 64,
                    },
                )
                components.append(
                    {
                        "name": name,
                        "mode": "REAL_COMPONENTS",
                        "version": "test-version",
                        "endpoint": endpoint,
                        "observed_at": "2026-07-31T00:00:00Z",
                        "health_check_id": f"probe-{name}",
                        "probe_evidence_path": f"probes/{name}.json",
                        "probe_evidence_sha256": sha256(probe_path),
                    }
                )
            write_json(
                root / "component-manifest.json",
                {
                    "run_id": "p6-08-test-run",
                    "observed_at": "2026-07-31T00:00:00Z",
                    "components": components,
                    "business_api_url": "http://127.0.0.1:18080/actuator/health",
                    "inference_service_url": "http://127.0.0.1:18081/health",
                    "object_storage_endpoint": "http://127.0.0.1:19000/health",
                },
            )
            write_json(
                root / "report.json",
                {
                    "status": "PASS",
                    "execution_mode": "REAL_COMPONENTS",
                    "evidence_immutable": True,
                    "run_id": "p6-08-test-run",
                    "started_at": "2026-07-31T00:00:00Z",
                    "finished_at": "2026-07-31T00:10:00Z",
                    "source_revision": "a" * 40,
                },
            )
            write_json(
                root / "lifecycle-report.json",
                {
                    "status": "PASS",
                    "stages": [{
                        "stage": stage,
                        "evidence_id": f"evidence-{index}",
                        "observed_at": "2026-07-31T00:00:00Z",
                    } for index, stage in enumerate((
                        "CANDIDATE_APPROVED", "DATASET_FROZEN", "TRAINING_SUCCEEDED",
                        "MODEL_APPROVED", "SHADOW_OBSERVED", "CANARY_GATED",
                        "PRODUCTION_ACTIVE", "ROLLBACK_COMPLETED",
                    ), start=1)],
                },
            )
            write_json(
                root / "traceability.json",
                {
                    "items": [{key: ["approval-1"] if key == "approval_ids" else "bound"
                               for key in (
                                   "capture_id", "image_sha256", "preprocess_version",
                                   "algorithm_version", "model_version_id",
                                   "dataset_version_id", "training_run_id",
                                   "approval_ids", "deployment_id",
                               )}],
                },
            )
            write_json(
                root / "runtime-evidence.json",
                {
                    "status": "PASS",
                    "historical_tasks_unchanged": True,
                    "evidence_immutable": True,
                    "model_package_signature_verified": True,
                    "rollback_executed": True,
                    "execution_id": "execution-1",
                    "event_chain_sha256": "b" * 64,
                    "observed_at": "2026-07-31T00:10:00Z",
                },
            )
            indexed = []
            for filename in sorted(set(MODULE.REQUIRED_FILES) - {"report.json"}):
                path = root / filename
                indexed.append({"file": filename, "sha256": sha256(path)})
            report = json.loads((root / "report.json").read_text(encoding="utf-8"))
            report["evidence_index"] = indexed
            report["evidence_index_sha256"] = hashlib.sha256(canonical(indexed)).hexdigest()
            write_json(root / "report.json", report)
            self.assertEqual([], validate(root))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
