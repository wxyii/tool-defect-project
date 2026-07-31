import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

from cryptography.hazmat.primitives import serialization


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "verify_p6_05", ROOT / "jobs/model-evaluator/verify_p6_05.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


class ModelRegistryVerifierTests(unittest.TestCase):
    def _package(
        self,
        root: Path,
        model_version: str,
        model_name: str,
        dataset_version: str,
        training_run: str,
        key_id: str,
        private_key,
    ) -> str:
        package = root / "packages" / model_version
        package.mkdir(parents=True)
        files = {
            "manifest.json": {
                "model_name": model_name,
                "model_version": model_version,
                "framework": "tensorflow",
                "framework_version": "2.13.0",
                "keras_version": "2.13.1",
                "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
                "input_spec": {
                    "shape": [256, 256, 3],
                    "dtype": "float32",
                    "color_space": "RGB",
                    "range": [0.0, 1.0],
                },
                "output_names": ["cla_out", "seg_out"],
                "label_map": {"0": "qualified", "1": "unqualified"},
                "preprocessor": {
                    "plugin_id": "tool-defect.basic",
                    "plugin_version": "1.0.0",
                    "config_hash": "sha256:" + "1" * 64,
                },
                "dataset_version": dataset_version,
                "source_run_id": training_run,
            },
            "model.json": {"class_name": "Functional", "config": {}},
            "weights.h5": "模型权重占位字节",
            "labels.json": {"0": "qualified", "1": "unqualified"},
            "preprocessing.json": {
                "plugin_id": "tool-defect.basic",
                "plugin_version": "1.0.0",
                "config_hash": "sha256:" + "1" * 64,
            },
            "metrics.json": {"status": "COMPLETE", "accuracy": 0.9},
        }
        for filename, value in files.items():
            path = package / filename
            if filename == "weights.h5":
                path.write_bytes(value.encode("utf-8"))
            else:
                write_json(path, value)
        (package / "environment.lock").write_text("python==3.11\n", encoding="utf-8")
        checksum_names = (
            "environment.lock",
            "labels.json",
            "manifest.json",
            "metrics.json",
            "model.json",
            "preprocessing.json",
            "weights.h5",
        )
        checksum_payload = "".join(
            f"{MODULE.sha256_file(package / filename)}  {filename}\n"
            for filename in checksum_names
        ).encode("utf-8")
        (package / "checksums.sha256").write_bytes(checksum_payload)
        signature = private_key.sign(checksum_payload)
        write_json(
            package / "signature.sig",
            {
                "algorithm": "ed25519",
                "key_id": key_id,
                "signature_base64": base64.b64encode(signature).decode("ascii"),
            },
        )
        return hashlib.sha256(checksum_payload).hexdigest()

    def _registry(self, root: Path) -> tuple[Path, Path]:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        package_dir = root / "registry"
        package_dir.mkdir()
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        key_id = "test-key"
        write_json(package_dir / "trusted-keys.json", {key_id: base64.b64encode(public_key).decode("ascii")})
        dataset_version = str(uuid.uuid4())
        training_one = str(uuid.uuid4())
        training_two = str(uuid.uuid4())
        model_one = str(uuid.uuid4())
        model_two = str(uuid.uuid4())
        hash_one = self._package(package_dir, "1", "multitask", dataset_version, training_one, key_id, private_key)
        hash_two = self._package(package_dir, "2", "multitask", dataset_version, training_two, key_id, private_key)
        model_records = []
        approval_records = []
        for index, (model_id, version, training_id, package_hash, registrar) in enumerate(
            ((model_one, "1", training_one, hash_one, "registrar-one"), (model_two, "2", training_two, hash_two, "registrar-two")),
            start=1,
        ):
            evaluation = package_dir / f"evaluation-{version}.json"
            threshold = package_dir / f"threshold-{version}.json"
            write_json(evaluation, {"status": "COMPLETE", "model_version": version})
            write_json(threshold, {"status": "APPROVED", "schema_version": "p6-04-production-gate.v1"})
            sbom = package_dir / f"sbom-{version}.cdx.json"
            write_json(
                sbom,
                {
                    "bomFormat": "CycloneDX",
                    "specVersion": "1.5",
                    "serialNumber": f"urn:uuid:{uuid.uuid4()}",
                    "components": [{"name": "tensorflow", "version": "2.13.0", "purl": "pkg:pypi/tensorflow@2.13.0"}],
                },
            )
            quality_id = f"approval-quality-{version}"
            release_id = f"approval-release-{version}"
            quality_evidence = package_dir / f"approval-evidence-quality-{version}.json"
            release_evidence = package_dir / f"approval-evidence-release-{version}.json"
            write_json(quality_evidence, {"approval_id": quality_id, "status": "PASS"})
            write_json(release_evidence, {"approval_id": release_id, "status": "PASS"})
            approval_records.extend(
                [
                    {
                        "approval_id": quality_id,
                        "model_version_id": model_id,
                        "role": "QUALITY_APPROVER",
                        "decision": "APPROVE",
                        "actor_id": f"quality-{version}",
                        "approved_at": "2026-07-31T01:00:00Z",
                        "independent": True,
                        "evidence_path": quality_evidence.name,
                        "evidence_sha256": MODULE.sha256_file(quality_evidence),
                    },
                    {
                        "approval_id": release_id,
                        "model_version_id": model_id,
                        "role": "MODEL_RELEASE_APPROVER",
                        "decision": "APPROVE",
                        "actor_id": f"release-{version}",
                        "approved_at": "2026-07-31T02:00:00Z",
                        "independent": True,
                        "evidence_path": release_evidence.name,
                        "evidence_sha256": MODULE.sha256_file(release_evidence),
                    },
                ]
            )
            model_records.append(
                {
                    "model_version_id": model_id,
                    "model_name": "multitask",
                    "model_version": version,
                    "state": "APPROVED",
                    "registered_by": registrar,
                    "training_run_id": training_id,
                    "dataset_version_id": dataset_version,
                    "package_dir": f"packages/{version}",
                    "package_sha256": package_hash,
                    "sbom_path": f"sbom-{version}.cdx.json",
                    "sbom_sha256": MODULE.sha256_file(sbom),
                    "signature_key_id": key_id,
                    "evaluation_report_path": f"evaluation-{version}.json",
                    "evaluation_report_sha256": MODULE.sha256_file(evaluation),
                    "threshold_gate_path": f"threshold-{version}.json",
                    "threshold_gate_sha256": MODULE.sha256_file(threshold),
                    "approval_ids": [quality_id, release_id],
                }
            )
        write_json(package_dir / "registry.json", {"schema_version": "p6-05-model-registry.v1", "status": "COMPLETE", "models": model_records})
        write_json(package_dir / "approvals.json", {"approvals": approval_records})
        write_json(
            package_dir / "aliases.json",
            {
                "aliases": [
                    {"alias": "production", "model_version_id": model_two, "package_sha256": hash_two, "immutable": True},
                    {"alias": "stable-previous", "model_version_id": model_one, "package_sha256": hash_one, "immutable": True},
                ]
            },
        )
        write_json(package_dir / "provenance.json", {"immutable": True, "production_claim_allowed": False, "code_commit": "a" * 40})
        write_json(package_dir / "report.json", {"status": "COMPLETE", "immutable": True, "production_release_allowed": True})
        return package_dir, package_dir / "trusted-keys.json"

    def test_missing_registry_is_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = MODULE.verify_package(Path(temporary), None)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertGreater(result["error_count"], 0)

    def test_signed_registry_and_aliases_pass_then_tampering_blocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            package_dir, trusted_keys = self._registry(Path(temporary))
            result = MODULE.verify_package(package_dir, trusted_keys)
            self.assertEqual(result["status"], "COMPLETE", result)
            (package_dir / "packages/2/weights.h5").write_bytes(b"tampered")
            blocked = MODULE.verify_package(package_dir, trusted_keys)
            self.assertEqual(blocked["status"], "BLOCKED")
            self.assertTrue(any("model_package_verification_failed" in item for item in blocked["errors"]))


if __name__ == "__main__":
    unittest.main()
