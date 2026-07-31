#!/usr/bin/env python3
"""P6-04 严格门槛验证器测试。"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

JOB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(JOB_ROOT))

import verify_p6_04  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class VerifyP604Tests(unittest.TestCase):
    def test_missing_package_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p6-04-missing-") as temp:
            result = verify_p6_04.verify_package(Path(temp))
        self.assertEqual("BLOCKED", result["status"])
        self.assertGreater(result["error_count"], 0)

    def test_approved_gate_requires_three_distinct_independent_signoffs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p6-04-valid-") as temp:
            package = Path(temp)
            sample_ids = [f"sample-{index:02d}" for index in range(34)]
            evaluation = {
                "status": "COMPLETE", "candidate_count": 3, "fixed_test_samples_required": 34,
                "shared_test_sample_ids": sample_ids, "production_claim_allowed": False,
                "candidates": [
                    {"candidate_id": name, "status": "VERIFIED", "blockers": []}
                    for name in ("a", "b", "c")
                ],
                "results": [{"candidate_id": name} for name in ("a", "b", "c")],
            }
            polar = {
                "status": "COMPLETE", "model_version_target": 2, "production_claim_allowed": False,
                "provenance": {"immutable": True, "test_set": {"sample_count": 34, "mapping": {item: {} for item in sample_ids}}},
                "legacy_model_blockers": [{"code": "LEGACY_VERSION_REJECTED"}],
            }
            (package / "evaluation-report.json").write_text(json.dumps(evaluation), encoding="utf-8")
            (package / "polar-report.json").write_text(json.dumps(polar), encoding="utf-8")
            fixed_manifest = package / "fixed-test.csv"
            fixed_manifest.write_text("sample_id\n" + "\n".join(sample_ids) + "\n", encoding="utf-8")
            signoff_files = {}
            for role in ("quality", "process", "algorithm"):
                path = package / f"{role}-signoff.json"
                path.write_text(json.dumps({"role": role, "status": "APPROVED"}), encoding="utf-8")
                signoff_files[role] = path
            gate = {
                "schema_version": "p6-04-production-gate.v1", "state": "APPROVED",
                "production_claim_allowed": False,
                "evaluation_report_sha256": _sha256(package / "evaluation-report.json"),
                "polar_report_sha256": _sha256(package / "polar-report.json"),
                "fixed_test_manifest_path": fixed_manifest.name,
                "fixed_test_manifest_sha256": _sha256(fixed_manifest),
                "fixed_test_sample_ids": sample_ids,
                "repeatability": {"runs": 2, "max_absolute_delta": 0.001, "tolerance": 0.01, "sample_count": 34},
                "thresholds": {"classification_accuracy": {"minimum": 0.7}, "mean_iou": {"minimum": 0.5}},
                "signoffs": {
                    "quality": {"state": "APPROVED", "independent": True, "approved_by": "quality", "approved_at": "2026-07-31T00:00:00Z", "evidence_path": signoff_files["quality"].name, "evidence_sha256": _sha256(signoff_files["quality"])},
                    "process": {"state": "APPROVED", "independent": True, "approved_by": "process", "approved_at": "2026-07-31T00:00:00Z", "evidence_path": signoff_files["process"].name, "evidence_sha256": _sha256(signoff_files["process"])},
                    "algorithm": {"state": "APPROVED", "independent": True, "approved_by": "algorithm", "approved_at": "2026-07-31T00:00:00Z", "evidence_path": signoff_files["algorithm"].name, "evidence_sha256": _sha256(signoff_files["algorithm"])},
                },
            }
            (package / "production-threshold-gate.json").write_text(json.dumps(gate), encoding="utf-8")
            result = verify_p6_04.verify_package(package)
        self.assertEqual("COMPLETE", result["status"], result)
        self.assertEqual(0, result["error_count"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
