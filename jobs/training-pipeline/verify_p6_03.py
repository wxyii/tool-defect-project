#!/usr/bin/env python3
"""P6-03 训练运行的严格只读验证器。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "jobs" / "training-pipeline" / "controlled-output"
REQUIRED_JSON = (
    "job-provenance.json", "config.lock.json", "environment.lock.json",
    "resource-isolation.json", "report.json",
)
REQUIRED_ARTIFACTS = (
    "model.json", "weights.h5", "weights_last.h5", "stage1_last.h5", "stage2_last.h5",
    "history.csv", "history.json", "config.json", "manifest.csv", "environment.txt",
    "run_metadata.json",
)
HASH_CHUNK = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


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


def _path_from_value(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _select_run(output_dir: Path, run_id: Optional[str], errors: List[str]) -> Optional[Path]:
    if run_id:
        path = output_dir / run_id
        if not path.is_dir():
            errors.append(f"run_missing:{display_path(path)}")
            return None
        return path
    runs = sorted(path for path in output_dir.iterdir() if path.is_dir()) if output_dir.is_dir() else []
    if not runs:
        errors.append(f"no_training_runs:{display_path(output_dir)}")
        return None
    return runs[-1]


def verify_run(run_dir: Path) -> Dict[str, Any]:
    errors: List[str] = []
    for name in REQUIRED_JSON + REQUIRED_ARTIFACTS:
        if not (run_dir / name).is_file():
            errors.append(f"missing_file:{name}")
    if errors:
        return {"status": "BLOCKED", "run_id": run_dir.name, "errors": errors[:80], "error_count": len(errors)}

    provenance = read_json(run_dir / "job-provenance.json", errors)
    config_lock = read_json(run_dir / "config.lock.json", errors)
    environment_lock = read_json(run_dir / "environment.lock.json", errors)
    isolation = read_json(run_dir / "resource-isolation.json", errors)
    report = read_json(run_dir / "report.json", errors)
    metadata = read_json(run_dir / "run_metadata.json", errors)
    history = read_json(run_dir / "history.json", errors)

    if report.get("status") != "COMPLETE":
        errors.append(f"report:status={report.get('status', 'MISSING')}")
    if report.get("production_claim_allowed") is not False:
        errors.append("report:production_claim_must_be_false")
    if report.get("immutable") is not True:
        errors.append("report:immutable_marker_missing")
    if provenance.get("schema_version") != "p6-03-training-provenance.v1":
        errors.append("provenance:schema_mismatch")
    if provenance.get("immutable") is not True:
        errors.append("provenance:immutable_marker_missing")
    if provenance.get("production_claim_allowed") is not False:
        errors.append("provenance:production_claim_must_be_false")
    if provenance.get("two_stage_training") is not True:
        errors.append("provenance:two_stage_training_missing")
    if provenance.get("failure_checkpoint_required") is not True:
        errors.append("provenance:failure_checkpoint_policy_missing")
    if provenance.get("code", {}).get("commit") in (None, "", "unknown"):
        errors.append("provenance:code_commit_missing")
    if provenance.get("code", {}).get("worktree_clean") is not True:
        errors.append("provenance:worktree_not_clean")
    if not provenance.get("dataset_version_id"):
        errors.append("provenance:dataset_version_missing")
    if not provenance.get("dataset_manifest_sha256"):
        errors.append("provenance:dataset_manifest_hash_missing")
    if not provenance.get("initial_model_sha256"):
        errors.append("provenance:initial_model_hash_missing")
    if provenance.get("config_sha256") != sha256_text(canonical_json(config_lock)):
        errors.append("provenance:config_hash_mismatch")
    if provenance.get("environment_sha256") != sha256_text(canonical_json(environment_lock)):
        errors.append("provenance:environment_hash_mismatch")

    if isolation.get("status") != "ENFORCED":
        errors.append(f"resource_isolation:status={isolation.get('status', 'MISSING')}")
    if isolation.get("training_pool") == isolation.get("inference_pool"):
        errors.append("resource_isolation:pools_must_differ")
    if isolation.get("exclusive") is not True:
        errors.append("resource_isolation:exclusive_marker_missing")

    if metadata.get("status") != "completed":
        errors.append(f"run_metadata:status={metadata.get('status', 'MISSING')}")
    if metadata.get("output_names") != ["cla_out", "seg_out"]:
        errors.append("run_metadata:multitask_outputs_mismatch")
    if not isinstance(history.get("stage1"), dict) or not isinstance(history.get("stage2"), dict):
        errors.append("history:both_stages_missing")
    if not history.get("stage1", {}).get("loss") or not history.get("stage2", {}).get("loss"):
        errors.append("history:both_stages_have_no_loss")

    dataset_manifest = _path_from_value(provenance.get("dataset_manifest", "")) if provenance.get("dataset_manifest") else None
    if dataset_manifest is None or not dataset_manifest.is_file():
        errors.append("dataset_manifest:missing")
    else:
        if sha256_file(dataset_manifest) != provenance.get("dataset_manifest_sha256"):
            errors.append("dataset_manifest:hash_mismatch")
    initial_model_dir = _path_from_value(provenance.get("initial_model_dir", "")) if provenance.get("initial_model_dir") else None
    if initial_model_dir is None:
        errors.append("initial_model:directory_missing")
    else:
        for name, expected in provenance.get("initial_model_sha256", {}).items():
            path = initial_model_dir / name
            if not path.is_file() or sha256_file(path) != expected:
                errors.append(f"initial_model:hash_mismatch:{name}")

    artifact_hashes = report.get("artifact_hashes", {})
    for name in REQUIRED_ARTIFACTS:
        path = run_dir / name
        observed = sha256_file(path)
        if artifact_hashes.get(name) != observed:
            errors.append(f"artifact_hash_mismatch:{name}")
    for name in ("weights.h5", "weights_last.h5", "stage1_last.h5", "stage2_last.h5"):
        if not (run_dir / name).read_bytes().startswith(b"\x89HDF\r\n\x1a\n"):
            errors.append(f"artifact_not_hdf5:{name}")
    try:
        model_json = json.loads((run_dir / "model.json").read_text(encoding="utf-8"))
        if not isinstance(model_json, dict) or "class_name" not in model_json:
            errors.append("artifact:model_json_not_keras_architecture")
    except Exception:
        errors.append("artifact:model_json_invalid")

    package_value = provenance.get("dataset_package_dir")
    if not package_value:
        errors.append("dataset_package:evidence_path_missing")
    else:
        package = _path_from_value(package_value)
        for name in ("report.json", "approval.json", "provenance.json", "manifest.csv"):
            if not (package / name).is_file():
                errors.append(f"dataset_package:missing_{name}")
        if (package / "report.json").is_file():
            dataset_report = read_json(package / "report.json", errors)
            if dataset_report.get("status") != "COMPLETE":
                errors.append("dataset_package:report_not_complete")
        if (package / "approval.json").is_file():
            dataset_approval = read_json(package / "approval.json", errors)
            if dataset_approval.get("state") != "APPROVED":
                errors.append("dataset_package:approval_not_approved")
            if dataset_approval.get("independent") is not True and dataset_approval.get("independent_approver") is not True:
                errors.append("dataset_package:independent_approval_missing")

    return {
        "status": "COMPLETE" if not errors else "BLOCKED",
        "run_id": run_dir.name,
        "accepted_artifacts": len(REQUIRED_ARTIFACTS) if not errors else 0,
        "error_count": len(errors),
        "errors": errors[:80],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="严格验证 P6-03 可复现训练运行")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    selection_errors: List[str] = []
    try:
        run_dir = _select_run(args.output_root.resolve(), args.run_id, selection_errors)
        result = verify_run(run_dir) if run_dir is not None else {
            "status": "BLOCKED", "errors": selection_errors, "error_count": len(selection_errors)
        }
    except Exception as exc:
        result = {"status": "BLOCKED", "errors": [f"verifier_exception:{type(exc).__name__}:{exc}"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
