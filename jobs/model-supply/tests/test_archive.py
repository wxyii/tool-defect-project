from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tool_defect.models.archive import (
    ArchiveLimits,
    ModelArchiveViolation,
    extract_verified_model_archive,
    verify_model_archive,
)


REQUIRED = (
    "manifest.json",
    "model.json",
    "weights.h5",
    "labels.json",
    "preprocessing.json",
    "metrics.json",
    "environment.lock",
    "checksums.sha256",
    "signature.sig",
    "sbom.json",
)


class ModelArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key = Ed25519PrivateKey.generate()
        public_key = self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.trusted_keys = {"test-key": public_key}

    def test_valid_signed_archive_returns_immutable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = self._write_archive(Path(directory))
            evidence = verify_model_archive(
                archive_path,
                declared_size_bytes=archive_path.stat().st_size,
                declared_sha256=sha256(archive_path.read_bytes()),
                trusted_public_keys=self.trusted_keys,
                limits=ArchiveLimits(maximum_compression_ratio=100),
            )

            self.assertEqual(evidence.signer_key_id, "test-key")
            self.assertEqual(evidence.manifest["model_name"], "external-demo")
            self.assertEqual(set(evidence.member_sha256), set(REQUIRED))

            target = Path(directory) / "extracted"
            extracted = extract_verified_model_archive(archive_path, target, evidence)
            self.assertEqual((extracted / "model.json").read_text(), "{}")

    def test_declared_hash_mismatch_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = self._write_archive(Path(directory))
            with self.assertRaises(ModelArchiveViolation) as caught:
                verify_model_archive(
                    archive_path,
                    declared_size_bytes=archive_path.stat().st_size,
                    declared_sha256="0" * 64,
                    trusted_public_keys=self.trusted_keys,
                )
            self.assertEqual(caught.exception.code, "ARCHIVE_SHA256_MISMATCH")

    def test_path_traversal_is_blocked_before_member_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = self._write_archive(Path(directory), extra_name="../escape.txt")
            with self.assertRaises(ModelArchiveViolation) as caught:
                self._verify(archive_path)
            self.assertEqual(caught.exception.code, "PATH_TRAVERSAL")

    def test_symlink_member_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = self._write_archive(Path(directory), special_symlink=True)
            with self.assertRaises(ModelArchiveViolation) as caught:
                self._verify(archive_path)
            self.assertEqual(caught.exception.code, "SPECIAL_FILE_MEMBER")

    def test_compression_bomb_is_blocked_by_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = self._write_archive(
                Path(directory),
                weights=b"A" * 65536,
            )
            with self.assertRaises(ModelArchiveViolation) as caught:
                verify_model_archive(
                    archive_path,
                    declared_size_bytes=archive_path.stat().st_size,
                    declared_sha256=sha256(archive_path.read_bytes()),
                    trusted_public_keys=self.trusted_keys,
                    limits=ArchiveLimits(maximum_compression_ratio=2),
                )
            self.assertEqual(caught.exception.code, "COMPRESSION_BOMB")

    def test_untrusted_signer_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = self._write_archive(Path(directory))
            with self.assertRaises(ModelArchiveViolation) as caught:
                verify_model_archive(
                    archive_path,
                    declared_size_bytes=archive_path.stat().st_size,
                    declared_sha256=sha256(archive_path.read_bytes()),
                    trusted_public_keys={"other-key": self.trusted_keys["test-key"]},
                )
            self.assertEqual(caught.exception.code, "SIGNER_NOT_TRUSTED")

    def test_supply_command_checks_policy_and_sbom(self) -> None:
        root = Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location(
            "verify_model_supply", root / "jobs/model-supply/verify_model_supply.py"
        )
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            archive_path = self._write_archive(temporary)
            trusted_path = temporary / "trusted-keys.json"
            trusted_path.write_text(
                json.dumps(
                    {
                        "test-key": base64.b64encode(self.trusted_keys["test-key"]).decode()
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = module.main(
                    [
                        "--archive",
                        str(archive_path),
                        "--declared-size",
                        str(archive_path.stat().st_size),
                        "--declared-sha256",
                        sha256(archive_path.read_bytes()),
                        "--trusted-keys",
                        str(trusted_path),
                    ]
                )
            self.assertEqual(result, 0, output.getvalue())
            self.assertIn('"status":"COMPLETE"', output.getvalue())

    def _verify(self, archive_path: Path):
        return verify_model_archive(
            archive_path,
            declared_size_bytes=archive_path.stat().st_size,
            declared_sha256=sha256(archive_path.read_bytes()),
            trusted_public_keys=self.trusted_keys,
        )

    def _write_archive(
        self,
        root: Path,
        *,
        weights: bytes = b"weights",
        extra_name: str | None = None,
        special_symlink: bool = False,
    ) -> Path:
        files: dict[str, bytes] = {
            "model.json": b"{}",
            "weights.h5": weights,
            "labels.json": b'{"0":"qualified"}',
            "preprocessing.json": b'{"plugin_id":"tool-defect.basic"}',
            "metrics.json": b'{"status":"COMPLETE"}',
            "environment.lock": b"python==3.11\n",
            "sbom.json": b'{"bomFormat":"CycloneDX","specVersion":"1.5","components":[{"name":"tensorflow","version":"2.13.0"}]}',
        }
        manifest_files = sorted((*files, "checksums.sha256", "signature.sig"))
        files["manifest.json"] = json.dumps(
            {
                "model_name": "external-demo",
                "model_version": "1.0.0",
                "framework": "tensorflow",
                "framework_version": "2.13.0",
                "preprocessor": {
                    "plugin_id": "tool-defect.basic",
                    "plugin_version": "1.0.0",
                },
                "files": manifest_files,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        checksums = "".join(
            f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
            for name in sorted(files)
        ).encode()
        files["checksums.sha256"] = checksums
        signature = self.private_key.sign(checksums)
        files["signature.sig"] = json.dumps(
            {
                "algorithm": "ed25519",
                "key_id": "test-key",
                "signature_base64": base64.b64encode(signature).decode(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

        archive_path = root / "model.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(files):
                archive.writestr(name, files[name])
            if extra_name is not None:
                archive.writestr(extra_name, b"escape")
            if special_symlink:
                info = zipfile.ZipInfo("linked")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, b"target")
        return archive_path


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


if __name__ == "__main__":
    unittest.main()
