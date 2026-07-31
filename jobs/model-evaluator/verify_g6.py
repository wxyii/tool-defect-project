#!/usr/bin/env python3
"""G6 阶段门禁：只接受 P6 全部真实证据闭合的不可变汇总。"""

from __future__ import annotations

import json
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = ROOT / "Docs/reports/P6-gate-acceptance.json"
TASKS = tuple(f"P6-0{index}" for index in range(1, 9))
FORBIDDEN = {"DRAFT", "BLOCKED", "HOLD", "IN_MEMORY", "SIMULATION", "PENDING"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REPORT_SCHEMA = "p6-g6-acceptance.v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def resolve_evidence_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = (ROOT / candidate).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return resolved


def verify_reference(reference: Any, errors: list[str], prefix: str) -> dict[str, Any] | None:
    if not isinstance(reference, dict):
        errors.append(f"{prefix}:must_be_object")
        return None
    path_value = reference.get("path")
    digest = reference.get("sha256")
    path = resolve_evidence_path(path_value)
    if path is None:
        errors.append(f"{prefix}:path_invalid")
        return None
    if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
        errors.append(f"{prefix}:sha256_invalid")
    elif not path.is_file():
        errors.append(f"{prefix}:file_missing")
    elif sha256_file(path) != digest:
        errors.append(f"{prefix}:sha256_mismatch")
    return {"path": path, "digest": digest}


def verify_gate_result(reference: Any, errors: list[str], prefix: str) -> None:
    resolved = verify_reference(reference, errors, prefix)
    if resolved is None:
        return
    path = resolved["path"]
    if path.suffix.lower() != ".json" or not path.is_file():
        errors.append(f"{prefix}:gate_result_must_be_json")
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append(f"{prefix}:gate_result_invalid_json")
        return
    if not isinstance(payload, dict):
        errors.append(f"{prefix}:gate_result_not_object")
    elif payload.get("status") not in {"PASS", "COMPLETE", "PASSED"}:
        errors.append(f"{prefix}:gate_result_not_pass")


def main() -> int:
    report_path = Path(os.environ.get("G6_REPORT", str(DEFAULT_REPORT))).resolve()
    errors: list[str] = []
    if not report_path.is_file():
        errors.append("missing_file:P6-gate-acceptance.json")
        report: dict[str, Any] = {}
    else:
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = {}
            errors.append("invalid_json:P6-gate-acceptance.json")

    if not isinstance(report, dict):
        errors.append("report_must_be_object")
        report = {}
    if report.get("schema_version") != REPORT_SCHEMA:
        errors.append("report_schema_not_v1")
    if report.get("contract_version") != "v1":
        errors.append("contract_version_not_v1")
    if report.get("status") != "PASS":
        errors.append("gate_status_not_PASS")
    if report.get("evidence_immutable") is not True:
        errors.append("evidence_not_immutable")
    for field in ("run_id", "created_at", "source_revision"):
        if not require_text(report.get(field)):
            errors.append(f"report_{field}_missing")
    task_entries = report.get("tasks")
    if not isinstance(task_entries, list):
        errors.append("tasks_missing")
        task_entries = []
    by_id = {
        entry.get("task_id"): entry
        for entry in task_entries
        if isinstance(entry, dict)
    }
    if len(by_id) != len(task_entries):
        errors.append("duplicate_task_id")
    for task_id in TASKS:
        entry = by_id.get(task_id)
        if not isinstance(entry, dict):
            errors.append(f"missing_task:{task_id}")
            continue
        if entry.get("status") != "PASS":
            errors.append(f"task_not_PASS:{task_id}")
        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"task_evidence_missing:{task_id}")
        else:
            for index, reference in enumerate(evidence):
                verify_reference(reference, errors, f"task_evidence:{task_id}:{index}")
        verify_gate_result(entry.get("gate_result"), errors, f"gate_result:{task_id}")
        for value in entry.values():
            if isinstance(value, str) and value.upper() in FORBIDDEN:
                errors.append(f"forbidden_state:{task_id}:{value}")
    if len(by_id) != len(TASKS):
        errors.append("task_count_not_8")

    payload = {
        "status": "PASS" if not errors else "BLOCKED",
        "report": str(report_path),
        "error_count": len(set(errors)),
        "errors": sorted(set(errors)),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
