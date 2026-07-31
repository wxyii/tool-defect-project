#!/usr/bin/env python3
"""P6-08 真实组件端到端证据门禁。

内存状态机、模拟器和干跑结果不能证明 P6-08。该入口只接受由真实业务 API、
训练/对象存储和推理运行时共同生成的不可变证据包；缺失证据明确返回 2。
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = ROOT / "jobs/model-evaluator/controlled-output/p6-08"
REQUIRED_FILES = (
    "component-manifest.json",
    "lifecycle-report.json",
    "traceability.json",
    "runtime-evidence.json",
    "report.json",
)
REQUIRED_COMPONENTS = {
    "business-api",
    "inference-service",
    "postgresql",
    "object-storage",
}
FORBIDDEN_MODES = {"IN_MEMORY", "SIMULATION", "MOCK", "DRY_RUN"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceError(Exception):
    pass


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvidenceError(f"missing_file:{path.name}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError(f"invalid_json:{path.name}") from error


def require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{name}:must_be_object")
    return value


def require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"{name}:must_be_nonempty_text")
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_evidence_path(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def verify_file_reference(
    root: Path,
    record: dict[str, Any],
    path_key: str,
    hash_key: str,
    errors: list[str],
) -> Path | None:
    path = safe_evidence_path(root, record.get(path_key))
    if path is None:
        errors.append(f"{path_key}:unsafe_or_missing")
        return None
    expected = record.get(hash_key)
    if not isinstance(expected, str) or SHA256.fullmatch(expected) is None:
        errors.append(f"{hash_key}:invalid")
    elif not path.is_file():
        errors.append(f"{path_key}:file_missing")
    elif sha256_file(path) != expected:
        errors.append(f"{hash_key}:mismatch")
    return path


def validate(evidence_root: Path) -> list[str]:
    errors: list[str] = []
    documents: dict[str, Any] = {}
    for filename in REQUIRED_FILES:
        try:
            documents[filename] = read_json(evidence_root / filename)
        except EvidenceError as error:
            errors.append(str(error))
    if errors:
        return errors

    manifest = require_object(documents["component-manifest.json"], "component-manifest")
    report = require_object(documents["report.json"], "report")
    lifecycle = require_object(documents["lifecycle-report.json"], "lifecycle")
    traceability = require_object(documents["traceability.json"], "traceability")
    runtime = require_object(documents["runtime-evidence.json"], "runtime")

    raw_mode = report.get("execution_mode")
    if not isinstance(raw_mode, str) or not raw_mode.strip():
        errors.append("report.execution_mode:must_be_nonempty_text")
        mode = ""
    else:
        mode = raw_mode
    if mode.upper() in FORBIDDEN_MODES:
        errors.append("execution_mode_is_not_real_components")
    if mode.upper() not in {"REAL_COMPONENTS", "PRODUCTION_EQUIVALENT"}:
        errors.append("execution_mode_not_production_equivalent")
    if report.get("status") != "PASS":
        errors.append("report_status_not_PASS")
    if report.get("evidence_immutable") is not True:
        errors.append("report_evidence_not_immutable")
    for field in ("run_id", "started_at", "finished_at", "source_revision"):
        try:
            require_text(report.get(field), f"report.{field}")
        except EvidenceError as error:
            errors.append(str(error))

    # 报告必须绑定四份核心证据的实际字节；只提交一份自声明 JSON 或改写后
    # 仍保留旧摘要不能通过。report.json 本身不纳入索引，避免循环哈希。
    evidence_index = report.get("evidence_index")
    if not isinstance(evidence_index, list) or not evidence_index:
        errors.append("report.evidence_index_missing")
    else:
        expected_files = set(REQUIRED_FILES) - {"report.json"}
        observed_files: set[str] = set()
        normalized_index: list[dict[str, str]] = []
        for index, item in enumerate(evidence_index):
            if not isinstance(item, dict):
                errors.append(f"report.evidence_index[{index}]:must_be_object")
                continue
            path = item.get("file")
            digest = item.get("sha256")
            if not isinstance(path, str) or path in observed_files:
                errors.append(f"report.evidence_index[{index}]:file_missing_or_duplicate")
                continue
            observed_files.add(path)
            if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
                errors.append(f"report.evidence_index[{index}]:sha256_invalid")
                continue
            resolved = safe_evidence_path(evidence_root, path)
            if resolved is None or not resolved.is_file():
                errors.append(f"report.evidence_index[{index}]:file_unavailable")
                continue
            if sha256_file(resolved) != digest:
                errors.append(f"report.evidence_index[{index}]:sha256_mismatch")
            normalized_index.append({"file": path, "sha256": digest})
        if observed_files != expected_files:
            errors.append("report.evidence_index:required_files_mismatch")
        expected_index_hash = hashlib.sha256(canonical_json(sorted(normalized_index, key=lambda item: item["file"]))).hexdigest()
        if report.get("evidence_index_sha256") != expected_index_hash:
            errors.append("report.evidence_index_sha256:mismatch")

    raw_components = manifest.get("components")
    if not isinstance(raw_components, list):
        errors.append("component_manifest.components_missing")
    else:
        components = {
            item.get("name")
            for item in raw_components
            if isinstance(item, dict)
        }
        missing = sorted(REQUIRED_COMPONENTS - components)
        if missing:
            errors.append("missing_real_components:" + ",".join(missing))
        for item in raw_components:
            if not isinstance(item, dict):
                errors.append("component_manifest_component_not_object")
                continue
            name = item.get("name", "unknown")
            mode = item.get("mode", "")
            if not isinstance(mode, str) or mode.upper() in FORBIDDEN_MODES:
                errors.append(f"component_not_real:{name}")
            if mode.upper() not in {"REAL_COMPONENTS", "PRODUCTION_EQUIVALENT"}:
                errors.append(f"component_mode_invalid:{name}")
            for field in ("version", "endpoint", "observed_at", "health_check_id"):
                try:
                    require_text(item.get(field), f"component.{name}.{field}")
                except EvidenceError as error:
                    errors.append(str(error))
            endpoint = item.get("endpoint")
            if isinstance(endpoint, str) and (".example" in endpoint or "example.com" in endpoint):
                errors.append(f"component_endpoint_placeholder:{name}")
            probe_path = verify_file_reference(
                evidence_root,
                item,
                "probe_evidence_path",
                "probe_evidence_sha256",
                errors,
            )
            if probe_path is not None:
                try:
                    probe = require_object(json.loads(probe_path.read_text(encoding="utf-8")), f"probe.{name}")
                    if probe.get("component") != name:
                        errors.append(f"probe_component_mismatch:{name}")
                    if probe.get("status") != "PASS":
                        errors.append(f"probe_status_not_PASS:{name}")
                    for field in ("request_id", "observed_at", "response_sha256"):
                        try:
                            require_text(probe.get(field), f"probe.{name}.{field}")
                        except EvidenceError as error:
                            errors.append(str(error))
                except (OSError, json.JSONDecodeError, EvidenceError):
                    errors.append(f"probe_invalid:{name}")

    if lifecycle.get("status") != "PASS":
        errors.append("lifecycle_report_not_PASS")
    stages = lifecycle.get("stages")
    required_stages = {
        "CANDIDATE_APPROVED",
        "DATASET_FROZEN",
        "TRAINING_SUCCEEDED",
        "MODEL_APPROVED",
        "SHADOW_OBSERVED",
        "CANARY_GATED",
        "PRODUCTION_ACTIVE",
        "ROLLBACK_COMPLETED",
    }
    if not isinstance(stages, list):
        errors.append("lifecycle.stages_missing")
    else:
        observed = {
            item.get("stage")
            for item in stages
            if isinstance(item, dict)
        }
        missing = sorted(required_stages - observed)
        if missing:
            errors.append("missing_lifecycle_stages:" + ",".join(missing))
        for index, item in enumerate(stages):
            if not isinstance(item, dict):
                errors.append(f"lifecycle.stages[{index}]:must_be_object")
                continue
            for field in ("stage", "evidence_id", "observed_at"):
                try:
                    require_text(item.get(field), f"lifecycle.stages[{index}].{field}")
                except EvidenceError as error:
                    errors.append(str(error))

    trace_items = traceability.get("items")
    if not isinstance(trace_items, list) or not trace_items:
        errors.append("traceability.items_missing")
    else:
        required_links = {
            "capture_id",
            "image_sha256",
            "preprocess_version",
            "algorithm_version",
            "model_version_id",
            "dataset_version_id",
            "training_run_id",
            "approval_ids",
            "deployment_id",
        }
        for index, item in enumerate(trace_items):
            if not isinstance(item, dict):
                errors.append(f"traceability.items[{index}]:must_be_object")
                continue
            missing = sorted(required_links - set(item))
            if missing:
                errors.append(
                    f"traceability.items[{index}].missing:" + ",".join(missing)
                )
            for key in required_links - {"approval_ids"}:
                if not isinstance(item.get(key), str) or not item[key].strip():
                    errors.append(f"traceability.items[{index}].{key}:empty")
            if not isinstance(item.get("approval_ids"), list) or not item["approval_ids"]:
                errors.append(f"traceability.items[{index}].approval_ids:empty")

    if runtime.get("status") != "PASS":
        errors.append("runtime_evidence_not_PASS")
    if runtime.get("historical_tasks_unchanged") is not True:
        errors.append("historical_tasks_not_proven_unchanged")
    if runtime.get("evidence_immutable") is not True:
        errors.append("runtime_evidence_not_immutable")
    if runtime.get("model_package_signature_verified") is not True:
        errors.append("model_package_signature_not_verified")
    if runtime.get("rollback_executed") is not True:
        errors.append("rollback_not_executed")
    for field in ("execution_id", "event_chain_sha256", "observed_at"):
        try:
            require_text(runtime.get(field), f"runtime.{field}")
        except EvidenceError as error:
            errors.append(str(error))

    # 严格入口要求真实组件地址也被记录，避免只提交一份离线自声明报告。
    for name in ("business_api_url", "inference_service_url", "object_storage_endpoint"):
        try:
            require_text(manifest.get(name), f"component-manifest.{name}")
        except EvidenceError as error:
            errors.append(str(error))
    if os.environ.get("P6_ALLOW_LOCAL_EVIDENCE") == "1":
        errors.append("local_evidence_override_forbidden")
    return sorted(set(errors))


def main() -> int:
    evidence_root = Path(os.environ.get("P6_08_EVIDENCE_DIR", str(DEFAULT_EVIDENCE))).resolve()
    errors = validate(evidence_root) if evidence_root.is_dir() else ["missing_directory:" + str(evidence_root)]
    payload = {
        "status": "PASS" if not errors else "BLOCKED",
        "evidence": str(evidence_root),
        "error_count": len(errors),
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
