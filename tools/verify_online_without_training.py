#!/usr/bin/env python3
"""R9 无训练在线隔离门禁。

该门禁区分离线研究资产和在线部署表面，检查后者是否仍包含数据集构建、
训练回调/配置/服务或第一版前端消费者；同时要求可审计的隔离验收证据。
缺少任一前置时返回 HOLD，绝不返回空目标成功。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

SCAN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "tools/dev/start-all.sh",
        ("dataset-builder", "DATASET_BUILDER", "TD_DATASET_", "TD_TRAINING_", "td.training."),
    ),
    (
        "deploy/compose",
        ("dataset-builder", "training-pipeline", "training-service", "TD_TRAINING_", "td.training."),
    ),
    (
        "deploy/monitoring",
        ("training-release", "tool.defect.dataset", "tool.defect.training"),
    ),
    (
        "services/business-api/src/main/java/com/tooldefect/business/training",
        (
            "@RestController",
            "@RestControllerAdvice",
            "@Service",
            "@Repository",
            "SCOPE_training:callback",
            "TD_TRAINING_",
            "td.training.",
            "/api/v1/training-runs",
        ),
    ),
    (
        "services/business-api/src/main/java/com/tooldefect/business/identity/infrastructure/SecurityConfiguration.java",
        ("/api/v1/training-runs", "training:create", "training:read"),
    ),
    (
        "apps/web-console/src",
        (
            "features/datasets",
            "features/training",
            "/api/v1/datasets",
            "/api/v1/dataset-versions",
            "/api/v1/training-runs",
        ),
    ),
)

REQUIRED_EVIDENCE = (
    "deployment_id",
    "tested_at",
    "approved_by",
    "observation_window",
    "training_service_absent",
    "dataset_builder_absent",
    "v2_detection",
    "legacy_write_410",
    "rollback_verified",
)


def main() -> int:
    residuals = _scan_residuals()
    if residuals:
        _print(
            {
                "status": "HOLD",
                "error_code": "ONLINE_TRAINING_SURFACE_REMAINS",
                "message": "在线表面仍包含训练/数据集依赖，未执行无训练在线验收",
                "residuals": residuals,
            }
        )
        return 2

    evidence_name = os.environ.get("TD_ONLINE_WITHOUT_TRAINING_EVIDENCE", "").strip()
    if not evidence_name:
        _print(
            {
                "status": "HOLD",
                "error_code": "ONLINE_ISOLATION_EVIDENCE_MISSING",
                "message": "缺少无训练隔离部署、观察窗和安全失败证据",
                "missing": ["TD_ONLINE_WITHOUT_TRAINING_EVIDENCE"],
            }
        )
        return 2

    evidence_path = Path(evidence_name)
    if not evidence_path.is_absolute():
        evidence_path = ROOT / evidence_path
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _print(
            {
                "status": "HOLD",
                "error_code": "ONLINE_ISOLATION_EVIDENCE_INVALID",
                "message": "无训练隔离证据不可读或不是有效 JSON",
            }
        )
        return 2

    errors = _validate_evidence(evidence)
    if errors:
        _print(
            {
                "status": "HOLD",
                "error_code": "ONLINE_ISOLATION_EVIDENCE_INCOMPLETE",
                "message": "无训练隔离证据缺少必需事实",
                "errors": errors,
            }
        )
        return 2

    _print(
        {
            "status": "COMPLETE",
            "deployment_id": evidence["deployment_id"],
            "tested_at": evidence["tested_at"],
            "approved_by": evidence["approved_by"],
        }
    )
    return 0


def _scan_residuals() -> list[dict[str, str]]:
    residuals: list[dict[str, str]] = []
    for relative, tokens in SCAN_RULES:
        target = ROOT / relative
        paths = [target] if target.is_file() else sorted(path for path in target.rglob("*") if path.is_file())
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                residuals.append({"path": str(path.relative_to(ROOT)), "token": "UNREADABLE"})
                continue
            for token in tokens:
                if token in text:
                    residuals.append({"path": str(path.relative_to(ROOT)), "token": token})
    return residuals


def _validate_evidence(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["根对象必须是 JSON 对象"]
    errors = [field for field in REQUIRED_EVIDENCE if field not in value]
    for field in ("deployment_id", "tested_at", "approved_by"):
        if field in value and (not isinstance(value[field], str) or not value[field].strip()):
            errors.append(f"{field} 必须是非空字符串")
    for field in ("training_service_absent", "dataset_builder_absent", "rollback_verified"):
        if value.get(field) is not True:
            errors.append(f"{field} 必须为 true")
    window = value.get("observation_window")
    if not isinstance(window, dict) or not all(isinstance(window.get(item), str) and window[item].strip() for item in ("started_at", "ended_at")):
        errors.append("observation_window 必须包含 started_at/ended_at")
    detection = value.get("v2_detection")
    if not isinstance(detection, dict) or not isinstance(detection.get("request_id"), str) or not detection["request_id"].strip():
        errors.append("v2_detection 必须包含 request_id")
    retired = value.get("legacy_write_410")
    if not isinstance(retired, dict) or retired.get("status") != 410 or retired.get("error_code") != "TD-LEGACY-FEATURE-RETIRED":
        errors.append("legacy_write_410 必须包含 410 和 TD-LEGACY-FEATURE-RETIRED")
    return errors


def _print(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    raise SystemExit(main())
