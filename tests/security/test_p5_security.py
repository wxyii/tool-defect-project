from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "src",
    ROOT / "services/inference-service/src",
):
    sys.path.insert(0, str(path))

from inference_service.storage.materializer import ObjectReference


class P5SecurityTest(unittest.TestCase):
    def test_inference_rejects_arbitrary_urls_and_local_paths(self):
        common = {
            "image_id": "019f0000-0000-7000-8000-000000000001",
            "sha256": "a" * 64,
            "media_type": "image/png",
            "size_bytes": 10,
        }
        for value in (
            "https://attacker.invalid/object",
            "http://127.0.0.1/internal",
            "/etc/passwd",
            "C:/Windows/System32/config",
            "../secret",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    ObjectReference(object_key=value, **common)

    def test_production_inference_has_no_database_or_internet_network(self):
        compose = (
            ROOT / "deploy/compose/production-security-baseline.yml"
        ).read_text(encoding="utf-8")
        start = compose.index("  inference-service:")
        end = compose.index("\n  postgres:", start)
        inference = compose[start:end]
        self.assertNotIn("business_database", inference)
        self.assertNotIn("TD_DATABASE_", inference)
        self.assertNotIn("ports:", inference)
        self.assertIn('TD_DISABLE_INTERNET_EGRESS: "true"', inference)
        self.assertIn("inference_queue", inference)
        self.assertIn("object_storage", inference)

    def test_device_revocation_and_internal_mtls_are_gateway_enforced(self):
        nginx = (ROOT / "deploy/gateway/nginx.conf").read_text(
            encoding="utf-8"
        )
        self.assertIn("ssl_crl /run/secrets/device-ca.crl", nginx)
        self.assertIn("X-Device-Certificate-Fingerprint", nginx)
        self.assertIn("X-Service-Certificate-Fingerprint", nginx)
        self.assertIn("ssl_verify_client optional", nginx)
        self.assertIn("listen 9443 ssl", nginx)
        self.assertIn(
            "ssl_client_certificate /run/secrets/service-ca.crt",
            nginx,
        )
        self.assertIn("ssl_crl /run/secrets/service-ca.crl", nginx)
        self.assertIn("ssl_verify_client on", nginx)

    def test_container_and_supply_chain_fail_closed(self):
        compose = (
            ROOT / "deploy/compose/production-security-baseline.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("read_only: true", compose)
        self.assertIn('cap_drop: ["ALL"]', compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertNotIn(":latest", compose)
        self.assertGreaterEqual(compose.count("@sha256:${"), 7)

        policy = (
            ROOT / "deploy/security/supply-chain-policy.json"
        ).read_text(encoding="utf-8")
        self.assertIn('"scheme": "sigstore-cosign"', policy)
        self.assertIn('"signature_algorithm": "ed25519"', policy)
        self.assertIn(
            '"verification_result_on_unknown_or_invalid": "HOLD"',
            policy,
        )
        self.assertIn('"production_alias_write": false', policy)

    def test_existing_model_gate_covers_tampering_and_unsigned_packages(self):
        source = (ROOT / "tests/test_trusted_model_package.py").read_text(
            encoding="utf-8"
        )
        verifier = (
            ROOT / "src/tool_defect/models/package.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "test_tampered_weight_and_mixed_architecture_are_rejected",
            source,
        )
        self.assertIn(
            "test_unsigned_and_wrong_framework_version_are_rejected",
            source,
        )
        self.assertIn("Ed25519PublicKey.from_public_bytes", verifier)
        self.assertIn("模型包数字签名验证失败", verifier)


if __name__ == "__main__":
    unittest.main()
