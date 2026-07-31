#!/usr/bin/env python3
"""P6-03 可复现 TensorFlow 两阶段训练作业入口。

本文件只负责作业级前置条件、来源锁、资源隔离记录和失败留证；实际模型训练
复用 ``src/tool_defect/training/retrain_multitask.py``，禁止用伪指标或文本文件
冒充模型检查点。任何缺失的数据集审批、初始化模型、资源隔离或可复现条件都会
生成非零 ``BLOCKED`` 报告，并且不会覆盖既有运行。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from importlib import metadata as package_metadata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tool_defect.config import load_config  # noqa: E402
from tool_defect.training.retrain_multitask import retrain_multitask  # noqa: E402


OUTPUT_DIR = REPO_ROOT / "jobs" / "training-pipeline" / "controlled-output"
HASH_CHUNK = 1024 * 1024
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _run_git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def code_snapshot() -> Dict[str, Any]:
    status = _run_git("status", "--porcelain", "--untracked-files=all")
    return {
        "commit": _run_git("rev-parse", "HEAD") or "unknown",
        "worktree_clean": not bool(status),
        "worktree_status_sha256": sha256_text(status),
        "diff_shortstat": _run_git("diff", "--shortstat"),
        "status_line_count": len(status.splitlines()) if status else 0,
    }


def environment_snapshot() -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {
        "python_version": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS", ""),
        "tf_num_intraop_threads": os.environ.get("TF_NUM_INTRAOP_THREADS", ""),
        "tf_num_interop_threads": os.environ.get("TF_NUM_INTEROP_THREADS", ""),
    }
    for package_name in ("tensorflow", "keras", "numpy", "opencv-python", "Pillow"):
        try:
            snapshot[package_name] = package_metadata.version(package_name)
        except package_metadata.PackageNotFoundError:
            snapshot[package_name] = "not-installed"
    return snapshot


def model_hashes(model_dir: Path) -> Tuple[Dict[str, str], List[str]]:
    hashes: Dict[str, str] = {}
    errors: List[str] = []
    for name in ("model.json", "weights.h5"):
        path = model_dir / name
        if not path.is_file():
            errors.append(f"initial_model_missing:{display_path(path)}")
        else:
            hashes[name] = sha256_file(path)
    return hashes, errors


def _package_dir(dataset_version: Path) -> Path:
    resolved = dataset_version.resolve()
    if resolved.is_file():
        return resolved.parent
    if (resolved / "manifest.csv").is_file():
        return resolved
    nested = resolved / "production-candidate-v1"
    if (nested / "manifest.csv").is_file():
        return nested
    return resolved


def dataset_evidence(
    config: Any,
    dataset_version: Optional[Path],
) -> Tuple[Dict[str, Any], List[str]]:
    """读取并验证训练输入的不可变数据版本证据。"""

    errors: List[str] = []
    manifest = config.path("manifest")
    data_root = config.path("data")
    evidence: Dict[str, Any] = {
        "dataset_version_id": "",
        "manifest": display_path(manifest),
        "manifest_sha256": "",
        "data_root": display_path(data_root),
        "approved": False,
        "immutable": False,
        "package_dir": None,
    }
    if dataset_version is None:
        errors.append("dataset_version_missing")
    else:
        package = _package_dir(dataset_version)
        evidence["package_dir"] = display_path(package)
        package_manifest = package / "manifest.csv"
        report_path = package / "report.json"
        approval_path = package / "approval.json"
        provenance_path = package / "provenance.json"
        required = (package_manifest, report_path, approval_path, provenance_path)
        for path in required:
            if not path.is_file():
                errors.append(f"dataset_evidence_missing:{display_path(path)}")
        if package_manifest.is_file():
            manifest = package_manifest
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            report = {}
            errors.append("dataset_report_unreadable")
        try:
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
        except Exception:
            approval = {}
            errors.append("dataset_approval_unreadable")
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except Exception:
            provenance = {}
            errors.append("dataset_provenance_unreadable")
        if report.get("status") != "COMPLETE":
            errors.append(f"dataset_status:{report.get('status', 'MISSING')}")
        if approval.get("state") != "APPROVED":
            errors.append(f"dataset_approval_state:{approval.get('state', 'MISSING')}")
        if approval.get("independent") is not True and approval.get("independent_approver") is not True:
            errors.append("dataset_independent_approval_missing")
        if provenance.get("immutable") is not True:
            errors.append("dataset_immutable_marker_missing")
        evidence["dataset_version_id"] = provenance.get("version_name", package.name)
        evidence["approved"] = approval.get("state") == "APPROVED"
        evidence["immutable"] = provenance.get("immutable") is True
        if provenance.get("manifest_sha256") and package_manifest.is_file():
            observed_manifest_hash = sha256_file(package_manifest)
            if provenance["manifest_sha256"] != observed_manifest_hash:
                errors.append("dataset_manifest_hash_mismatch")
    if not manifest.is_file():
        errors.append(f"training_manifest_missing:{display_path(manifest)}")
    else:
        evidence["manifest"] = display_path(manifest)
        evidence["manifest_sha256"] = sha256_file(manifest)
    if not data_root.is_dir():
        errors.append(f"training_data_root_missing:{display_path(data_root)}")
    return evidence, errors


def resource_isolation_record(training_pool: str, inference_pool: str) -> Dict[str, Any]:
    if not training_pool or not inference_pool:
        raise ValueError("训练池和推理池不能为空")
    if training_pool == inference_pool:
        raise ValueError("训练池与推理池必须不同")
    # 只有平台显式注入不可伪造的执行证明时才标记 ENFORCED；本地默认只是声明。
    enforced = os.environ.get("TOOL_DEFECT_RESOURCE_ISOLATION") == "ENFORCED"
    return {
        "schema_version": "p6-03-resource-isolation.v1",
        "training_pool": training_pool,
        "inference_pool": inference_pool,
        "training_process_namespace": f"training:{training_pool}",
        "inference_process_namespace": f"inference:{inference_pool}",
        "exclusive": True,
        "status": "ENFORCED" if enforced else "DECLARED",
        "enforcement_source": "platform-attested-env" if enforced else "local-declaration-only",
        "production_claim_allowed": False,
    }


def preflight(
    config_path: Path,
    dataset_version: Optional[Path],
    init_model_dir: Optional[Path],
    training_pool: str,
    inference_pool: str,
) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    if not config_path.is_file():
        return {}, [f"config_missing:{display_path(config_path)}"]
    try:
        config = load_config(config_path)
    except Exception as exc:
        return {}, [f"config_invalid:{type(exc).__name__}:{exc}"]
    dataset, dataset_errors = dataset_evidence(config, dataset_version)
    errors.extend(dataset_errors)
    model_dir = Path(init_model_dir or config.path("multitask_model")).resolve()
    initial_hashes, model_errors = model_hashes(model_dir)
    errors.extend(model_errors)
    try:
        isolation = resource_isolation_record(training_pool, inference_pool)
    except ValueError as exc:
        isolation = {
            "schema_version": "p6-03-resource-isolation.v1",
            "status": "BLOCKED",
            "production_claim_allowed": False,
        }
        errors.append(f"resource_isolation_invalid:{exc}")
    return {
        "config": config,
        "config_values": config.values,
        "dataset": dataset,
        "initial_model_dir": model_dir,
        "initial_model_sha256": initial_hashes,
        "resource_isolation": isolation,
        "code": code_snapshot(),
        "environment": environment_snapshot(),
    }, errors


def _run_dir(output_root: Path, run_id: str, resume: Optional[Path]) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id 格式非法")
    if resume is not None:
        resolved = resume.resolve()
        return resolved if resolved.is_dir() else resolved.parent
    return output_root.resolve() / run_id


def _artifact_hashes(run_dir: Path) -> Dict[str, str]:
    names = (
        "model.json", "weights.h5", "weights_last.h5", "stage1_last.h5", "stage2_last.h5",
        "history.csv", "history.json", "config.json", "manifest.csv", "environment.txt",
        "run_metadata.json",
    )
    return {
        name: sha256_file(run_dir / name)
        for name in names
        if (run_dir / name).is_file()
    }


def _write_initial_locks(
    run_dir: Path,
    run_id: str,
    preflight_data: Dict[str, Any],
    config_path: Path,
    resume_from: Optional[Path],
) -> Dict[str, Any]:
    config_values = preflight_data.get("config_values", {})
    config_hash = sha256_text(canonical_json(config_values))
    environment = preflight_data.get("environment", {})
    code = preflight_data.get("code", {})
    dataset = preflight_data.get("dataset", {})
    provenance = {
        "schema_version": "p6-03-training-provenance.v1",
        "run_id": run_id,
        "task_type": "multitask",
        "dataset_version_id": dataset.get("dataset_version_id", ""),
        "dataset_manifest": dataset.get("manifest", ""),
        "dataset_manifest_sha256": dataset.get("manifest_sha256", ""),
        "dataset_package_dir": dataset.get("package_dir"),
        "config_path": display_path(config_path),
        "config_sha256": config_hash,
        "initial_model_dir": display_path(preflight_data.get("initial_model_dir", Path(""))),
        "initial_model_sha256": preflight_data.get("initial_model_sha256", {}),
        "random_seed": int(config_values.get("seed", 1)) if config_values else None,
        "code": code,
        "environment_sha256": sha256_text(canonical_json(environment)),
        "created_at": utc_now(),
        "started_at": None,
        "resume_from": display_path(resume_from) if resume_from else None,
        "two_stage_training": True,
        "failure_checkpoint_required": True,
        "immutable": True,
        "production_claim_allowed": False,
    }
    write_json(run_dir / "config.lock.json", config_values)
    write_json(run_dir / "environment.lock.json", environment)
    write_json(run_dir / "resource-isolation.json", preflight_data.get("resource_isolation", {}))
    write_json(run_dir / "job-provenance.json", provenance)
    return provenance


def _report(
    run_dir: Path,
    run_id: str,
    status: str,
    final_training_status: str,
    issues: List[str],
    provenance: Dict[str, Any],
    artifact_hashes: Dict[str, str],
) -> Dict[str, Any]:
    result = {
        "schema_version": "p6-03-training-report.v1",
        "run_id": run_id,
        "status": status,
        "final_training_status": final_training_status,
        "reproducibility_issues": len(issues),
        "reproducibility_details": issues,
        "artifact_hashes": artifact_hashes,
        "provenance_sha256": sha256_text(canonical_json(provenance)),
        "two_stage_training": True,
        "resume_supported": True,
        "failure_checkpoint_required": True,
        "production_claim_allowed": False,
        "immutable": True,
    }
    write_json(run_dir / "report.json", result)
    return result


def execute_training(
    config_path: Path,
    output_root: Path,
    run_id: str,
    dataset_version: Optional[Path],
    init_model_dir: Optional[Path],
    smoke: bool,
    resume: Optional[Path],
    training_pool: str,
    inference_pool: str,
) -> Tuple[int, Dict[str, Any]]:
    run_dir = _run_dir(output_root, run_id, resume)
    effective_run_id = run_dir.name if resume is not None else run_id
    if resume is None and run_dir.exists():
        return 2, {"status": "BLOCKED", "errors": [f"run_exists:{display_path(run_dir)}"]}
    run_dir.mkdir(parents=True, exist_ok=True)
    existing_provenance: Dict[str, Any] = {}
    if resume is not None and (run_dir / "job-provenance.json").is_file():
        try:
            existing_provenance = json.loads(
                (run_dir / "job-provenance.json").read_text(encoding="utf-8")
            )
        except Exception:
            existing_provenance = {}
    preflight_data, issues = preflight(
        config_path.resolve(), dataset_version, init_model_dir, training_pool, inference_pool
    )
    provenance = _write_initial_locks(run_dir, effective_run_id, preflight_data, config_path.resolve(), resume)
    provenance["started_at"] = utc_now()
    write_json(run_dir / "job-provenance.json", provenance)
    if issues:
        result = _report(run_dir, effective_run_id, "BLOCKED", "PRECONDITION_FAILED", issues, provenance, {})
        return 1, result

    if resume is not None:
        for field in ("config_sha256", "dataset_manifest_sha256", "initial_model_sha256"):
            if existing_provenance.get(field) and existing_provenance.get(field) != provenance.get(field):
                issue = f"resume_{field}_mismatch"
                result = _report(run_dir, effective_run_id, "BLOCKED", "RESUME_REJECTED", [issue], provenance, {})
                return 1, result

    try:
        returned_dir = retrain_multitask(
            config_path=config_path.resolve(),
            init_model_dir=preflight_data["initial_model_dir"],
            output_root=output_root.resolve(),
            run_id=effective_run_id,
            smoke=smoke,
            resume=resume,
        )
        run_dir = Path(returned_dir).resolve()
        artifact_hashes = _artifact_hashes(run_dir)
        required = {
            "model.json", "weights.h5", "weights_last.h5", "stage1_last.h5", "stage2_last.h5",
            "history.csv", "history.json", "config.json", "manifest.csv", "environment.txt",
            "run_metadata.json",
        }
        missing = sorted(required - set(artifact_hashes))
        if missing:
            issues.append(f"training_artifacts_missing:{','.join(missing)}")
        metadata_path = run_dir / "run_metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() else {}
        if metadata.get("status") != "completed":
            issues.append(f"training_metadata_status:{metadata.get('status', 'MISSING')}")
        if not preflight_data["code"].get("worktree_clean"):
            issues.append("uncommitted_changes:工作树存在未提交改动")
        if preflight_data["resource_isolation"].get("status") != "ENFORCED":
            issues.append("resource_isolation_not_attested:仅有本地声明")
        provenance["completed_at"] = utc_now()
        provenance["actual_run_dir"] = display_path(run_dir)
        provenance["artifact_hashes"] = artifact_hashes
        write_json(run_dir / "job-provenance.json", provenance)
        result = _report(
            run_dir,
            effective_run_id,
            "COMPLETE" if not issues else "BLOCKED",
            "SUCCEEDED",
            issues,
            provenance,
            artifact_hashes,
        )
        return 0 if result["status"] == "COMPLETE" else 1, result
    except Exception as exc:
        failure = {
            "schema_version": "p6-03-failure.v1",
            "run_id": effective_run_id,
            "status": "BLOCKED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "failed_at": utc_now(),
            "checkpoint_directory": display_path(run_dir),
            "production_claim_allowed": False,
        }
        write_json(run_dir / "failure.json", failure)
        provenance["failed_at"] = utc_now()
        write_json(run_dir / "job-provenance.json", provenance)
        result = _report(run_dir, effective_run_id, "BLOCKED", "FAILED", [f"training_failed:{type(exc).__name__}:{exc}"], provenance, _artifact_hashes(run_dir))
        return 1, result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="执行 P6-03 可复现两阶段训练作业")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "configs/retrain_multitask.json")
    parser.add_argument("--dataset-version", type=Path)
    parser.add_argument("--init-model-dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--run-id", default=f"train-{int(time.time())}")
    parser.add_argument("--smoke", action="store_true", help="只运行真实两阶段各一轮，用于流程验证")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--training-pool", default="ml-training")
    parser.add_argument("--inference-pool", default="ml-inference")
    args = parser.parse_args(argv)
    try:
        code, result = execute_training(
            config_path=args.config,
            output_root=args.output_root,
            run_id=args.run_id,
            dataset_version=args.dataset_version,
            init_model_dir=args.init_model_dir,
            smoke=args.smoke,
            resume=args.resume,
            training_pool=args.training_pool,
            inference_pool=args.inference_pool,
        )
    except Exception as exc:
        result = {"status": "BLOCKED", "error_type": type(exc).__name__, "error": str(exc)}
        code = 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
