#!/usr/bin/env python3
"""P6-04 统一评估、极坐标重标定和生产门槛的严格验证器。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = REPO_ROOT / "jobs" / "model-evaluator" / "controlled-output" / "p6-04"
REQUIRED_FILES = ("evaluation-report.json", "polar-report.json", "production-threshold-gate.json")
SHA_CHUNK = 1024 * 1024
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(SHA_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, errors: List[str]) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{path.name}:json_{type(exc).__name__}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.name}:root_not_object")
        return {}
    return value


def safe_relative_file(package_dir: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = (package_dir / candidate).resolve()
    try:
        resolved.relative_to(package_dir.resolve())
    except ValueError:
        return None
    return resolved


def verify_package(package_dir: Path) -> Dict[str, Any]:
    errors: List[str] = []
    missing = [name for name in REQUIRED_FILES if not (package_dir / name).is_file()]
    errors.extend(f"missing_file:{name}" for name in missing)
    if errors:
        return {"status": "BLOCKED", "error_count": len(errors), "errors": errors}

    evaluation = read_json(package_dir / "evaluation-report.json", errors)
    polar = read_json(package_dir / "polar-report.json", errors)
    gate = read_json(package_dir / "production-threshold-gate.json", errors)

    if evaluation.get("status") != "COMPLETE":
        errors.append(f"evaluation:status={evaluation.get('status', 'MISSING')}")
    if evaluation.get("candidate_count") != 3:
        errors.append("evaluation:candidate_count_must_be_3")
    if evaluation.get("fixed_test_samples_required") != 34:
        errors.append("evaluation:fixed_test_sample_requirement_mismatch")
    shared_ids = evaluation.get("shared_test_sample_ids")
    if not isinstance(shared_ids, list) or len(shared_ids) != 34 or len(set(shared_ids)) != 34:
        errors.append("evaluation:fixed_test_set_missing_or_duplicate")
    candidates = evaluation.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 3:
        errors.append("evaluation:candidate_audits_incomplete")
    else:
        for candidate in candidates:
            if candidate.get("status") != "VERIFIED":
                errors.append(f"evaluation:candidate_not_verified:{candidate.get('candidate_id', 'MISSING')}")
            if candidate.get("blockers"):
                errors.append(f"evaluation:candidate_blocked:{candidate.get('candidate_id', 'MISSING')}")
    results = evaluation.get("results")
    if not isinstance(results, list) or len(results) != 3:
        errors.append("evaluation:three_results_missing")
    if evaluation.get("production_claim_allowed") is not False:
        errors.append("evaluation:production_claim_must_be_false")

    if polar.get("status") != "COMPLETE":
        errors.append(f"polar:status={polar.get('status', 'MISSING')}")
    if polar.get("model_version_target") != 2:
        errors.append("polar:model_version_2_required")
    if polar.get("production_claim_allowed") is not False:
        errors.append("polar:production_claim_must_be_false")
    polar_provenance = polar.get("provenance", {})
    if polar_provenance.get("immutable") is not True:
        errors.append("polar:immutable_marker_missing")
    test_set = polar_provenance.get("test_set", {})
    mapping = test_set.get("mapping", {}) if isinstance(test_set, dict) else {}
    if test_set.get("sample_count") != 34 or len(mapping) != 34:
        errors.append("polar:fixed_test_set_incomplete")
    legacy_blockers = polar.get("legacy_model_blockers", [])
    if not legacy_blockers:
        errors.append("polar:legacy_version_rejection_evidence_missing")
    elif not any(item.get("code") == "LEGACY_VERSION_REJECTED" for item in legacy_blockers):
        errors.append("polar:legacy_version_rejection_missing")

    if gate.get("schema_version") != "p6-04-production-gate.v1":
        errors.append("gate:schema_mismatch")
    if gate.get("state") != "APPROVED":
        errors.append(f"gate:state={gate.get('state', 'MISSING')}")
    if gate.get("production_claim_allowed") is not False:
        errors.append("gate:production_claim_must_be_false")
    if gate.get("evaluation_report_sha256") != sha256_file(package_dir / "evaluation-report.json"):
        errors.append("gate:evaluation_report_hash_mismatch")
    if gate.get("polar_report_sha256") != sha256_file(package_dir / "polar-report.json"):
        errors.append("gate:polar_report_hash_mismatch")
    fixed_manifest_path = safe_relative_file(package_dir, gate.get("fixed_test_manifest_path"))
    fixed_manifest_hash = gate.get("fixed_test_manifest_sha256")
    if fixed_manifest_path is None:
        errors.append("gate:fixed_test_manifest_path_missing")
    elif not fixed_manifest_path.is_file():
        errors.append("gate:fixed_test_manifest_file_missing")
    elif not isinstance(fixed_manifest_hash, str) or SHA256.fullmatch(fixed_manifest_hash) is None:
        errors.append("gate:fixed_test_manifest_hash_invalid")
    elif sha256_file(fixed_manifest_path) != fixed_manifest_hash:
        errors.append("gate:fixed_test_manifest_hash_mismatch")
    if gate.get("fixed_test_sample_ids") != shared_ids:
        errors.append("gate:fixed_test_sample_order_mismatch")
    repeatability = gate.get("repeatability", {})
    if repeatability.get("runs", 0) < 2:
        errors.append("gate:repeatability_requires_two_runs")
    if repeatability.get("max_absolute_delta") is None or repeatability.get("tolerance") is None:
        errors.append("gate:repeatability_tolerance_missing")
    elif float(repeatability["max_absolute_delta"]) > float(repeatability["tolerance"]):
        errors.append("gate:repeatability_tolerance_exceeded")
    if repeatability.get("sample_count") != 34:
        errors.append("gate:repeatability_sample_count_mismatch")
    thresholds = gate.get("thresholds")
    if not isinstance(thresholds, dict) or not thresholds:
        errors.append("gate:versioned_thresholds_missing")
    signoffs = gate.get("signoffs")
    required_roles = ("quality", "process", "algorithm")
    if not isinstance(signoffs, dict):
        errors.append("gate:signoffs_missing")
    else:
        approvers = []
        for role in required_roles:
            record = signoffs.get(role, {})
            if record.get("state") != "APPROVED":
                errors.append(f"gate:signoff_not_approved:{role}")
            if record.get("independent") is not True:
                errors.append(f"gate:independent_signoff_missing:{role}")
            if not (record.get("approved_by") or "").strip() or not (record.get("approved_at") or "").strip():
                errors.append(f"gate:signoff_identity_missing:{role}")
            evidence_path = safe_relative_file(package_dir, record.get("evidence_path"))
            evidence_hash = record.get("evidence_sha256")
            if evidence_path is None:
                errors.append(f"gate:signoff_evidence_path_missing:{role}")
            elif not evidence_path.is_file():
                errors.append(f"gate:signoff_evidence_file_missing:{role}")
            elif not isinstance(evidence_hash, str) or SHA256.fullmatch(evidence_hash) is None:
                errors.append(f"gate:signoff_evidence_hash_invalid:{role}")
            elif sha256_file(evidence_path) != evidence_hash:
                errors.append(f"gate:signoff_evidence_hash_mismatch:{role}")
            approvers.append(record.get("approved_by"))
        if len(set(approvers)) != len(required_roles):
            errors.append("gate:signoff_roles_must_be_distinct")

    return {
        "status": "COMPLETE" if not errors else "BLOCKED",
        "package": str(package_dir),
        "candidate_count": len(candidates) if isinstance(candidates, list) else 0,
        "fixed_test_samples": len(shared_ids) if isinstance(shared_ids, list) else 0,
        "error_count": len(errors),
        "errors": errors[:80],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="严格验证 P6-04 评估和生产门槛证据")
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    args = parser.parse_args(argv)
    try:
        result = verify_package(args.package_dir.resolve())
    except Exception as exc:
        result = {"status": "BLOCKED", "errors": [f"verifier_exception:{type(exc).__name__}:{exc}"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
