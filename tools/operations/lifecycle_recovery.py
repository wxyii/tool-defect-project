#!/usr/bin/env python3
"""对象生命周期、容量和联合恢复点的安全实现。

所有清理结果都只是候选计划；本工具不删除生产对象。恢复必须写入空的
隔离目录，并在复制后重新计算每个文件的 SHA-256。
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from typing import Iterable, Mapping


SCHEMA_VERSION = "tool-defect-recovery/v1"
REQUIRED_COMPONENTS = frozenset(
    {"database", "objects", "models", "datasets", "approvals", "reviews"}
)
PROTECTED_KINDS = frozenset(
    {"RAW_IMAGE", "REVIEW_MASK", "DATASET", "MODEL_PACKAGE"}
)


class RecoveryError(ValueError):
    """恢复点不完整、不可信或无法安全恢复。"""


@dataclass(frozen=True)
class CapacityInput:
    stations: int
    captures_per_station_per_day: int
    raw_bytes_per_capture: int
    derived_bytes_per_capture: int
    online_retention_days: int
    archive_retention_days: int
    database_bytes: int
    model_and_dataset_bytes: int
    backup_copies: int
    headroom_ratio: float
    target_signed: bool = False


def calculate_capacity(value: CapacityInput) -> dict[str, object]:
    """计算在线、归档、备份和增长余量，未签字目标显式保持待签字。"""

    integers = (
        value.stations,
        value.captures_per_station_per_day,
        value.raw_bytes_per_capture,
        value.derived_bytes_per_capture,
        value.online_retention_days,
        value.archive_retention_days,
        value.database_bytes,
        value.model_and_dataset_bytes,
        value.backup_copies,
    )
    if any(item < 0 for item in integers):
        raise ValueError("容量输入不能为负数")
    if value.stations == 0 or value.captures_per_station_per_day == 0:
        raise ValueError("工位数和每日采集量必须大于零")
    if not 0 <= value.headroom_ratio <= 3:
        raise ValueError("增长余量比例必须位于 0 到 3")

    daily_raw = (
        value.stations
        * value.captures_per_station_per_day
        * value.raw_bytes_per_capture
    )
    daily_derived = (
        value.stations
        * value.captures_per_station_per_day
        * value.derived_bytes_per_capture
    )
    online = (daily_raw + daily_derived) * value.online_retention_days
    archive = daily_raw * value.archive_retention_days
    protected = value.database_bytes + value.model_and_dataset_bytes
    primary = online + archive + protected
    backups = primary * value.backup_copies
    required = int((primary + backups) * (1 + value.headroom_ratio))
    return {
        "schema_version": "tool-defect-capacity/v1",
        "status": "SIGNED" if value.target_signed else "PENDING_SIGNOFF",
        "daily_raw_bytes": daily_raw,
        "daily_derived_bytes": daily_derived,
        "online_bytes": online,
        "archive_bytes": archive,
        "protected_metadata_bytes": protected,
        "backup_bytes": backups,
        "required_bytes_with_headroom": required,
        "formula": (
            "((每日原图+每日派生图)*在线天数"
            "+每日原图*归档天数+数据库+模型数据集)"
            "*(1+备份份数)*(1+增长余量)"
        ),
    }


def plan_lifecycle(
    records: Iterable[Mapping[str, object]],
    *,
    now: datetime,
    archive_after_days: int,
    cleanup_after_days: int,
    orphan_audit_days: int,
) -> list[dict[str, object]]:
    """生成生命周期候选，不执行删除并保护所有引用和不可变资产。"""

    if min(archive_after_days, cleanup_after_days, orphan_audit_days) < 0:
        raise ValueError("生命周期天数不能为负数")
    if cleanup_after_days < archive_after_days:
        raise ValueError("清理期限不能早于归档期限")
    record_list = list(records)
    known = {
        str(record.get("object_key", ""))
        for record in record_list
        if record.get("object_key")
    }
    referenced_by = {
        str(reference)
        for record in record_list
        for reference in record.get("references", [])
    }
    result: list[dict[str, object]] = []
    for record in record_list:
        object_key = _safe_relative(str(record.get("object_key", "")))
        kind = str(record.get("kind", ""))
        state = str(record.get("state", "ACTIVE"))
        created_at = _parse_time(str(record.get("created_at", "")))
        age_days = max(0, int((now - created_at).total_seconds() // 86400))
        references = tuple(str(item) for item in record.get("references", []))
        missing = sorted(reference for reference in references if reference not in known)

        action = "RETAIN"
        reason = "仍在在线保留期"
        if missing:
            action = "HOLD"
            reason = f"引用闭包缺失：{', '.join(missing)}"
        elif kind in PROTECTED_KINDS:
            reason = "原图、人工掩膜、数据集或模型属于受保护事实"
        elif object_key in referenced_by:
            reason = "对象仍被业务事实或不可变清单引用"
        elif state == "ORPHAN":
            if age_days >= orphan_audit_days:
                action = "CLEANUP_CANDIDATE"
                reason = "孤儿已超过审计观察窗且无引用"
            else:
                action = "QUARANTINE"
                reason = "孤儿仍在审计观察窗"
        elif age_days >= cleanup_after_days:
            action = "CLEANUP_CANDIDATE"
            reason = "无引用派生对象超过清理期限"
        elif age_days >= archive_after_days:
            action = "ARCHIVE_CANDIDATE"
            reason = "无引用派生对象超过归档期限"

        result.append(
            {
                "object_key": object_key,
                "kind": kind,
                "age_days": age_days,
                "action": action,
                "reason": reason,
                "destructive_action_executed": False,
            }
        )
    return sorted(result, key=lambda item: str(item["object_key"]))


def create_recovery_point(
    source_root: Path,
    manifest_path: Path,
    *,
    recovery_point_id: str,
    created_at: datetime,
) -> dict[str, object]:
    """从六类组件和控制总数建立统一恢复点清单。"""

    source_root = source_root.resolve()
    if not recovery_point_id or "/" in recovery_point_id or "\\" in recovery_point_id:
        raise RecoveryError("恢复点标识不能为空或包含路径分隔符")
    evidence_path = source_root / "recovery-evidence.json"
    evidence = _load_json(evidence_path)
    _validate_evidence(evidence)

    components: dict[str, list[dict[str, object]]] = {}
    for component in sorted(REQUIRED_COMPONENTS):
        component_root = source_root / component
        if not component_root.is_dir():
            raise RecoveryError(f"恢复点缺少组件目录：{component}")
        files = sorted(path for path in component_root.rglob("*") if path.is_file())
        if not files:
            raise RecoveryError(f"恢复点组件为空：{component}")
        entries: list[dict[str, object]] = []
        for path in files:
            if path.is_symlink():
                raise RecoveryError(f"恢复点禁止符号链接：{path}")
            relative = path.relative_to(source_root).as_posix()
            _safe_relative(relative)
            entries.append(
                {
                    "path": relative,
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
        components[component] = entries

    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "recovery_point_id": recovery_point_id,
        "created_at": created_at.astimezone(UTC).isoformat(),
        "components": components,
        "control_totals": evidence["control_totals"],
        "reference_closure": evidence["reference_closure"],
        "evidence_sha256": _sha256(evidence_path),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    verify_recovery_point(source_root, manifest)
    return manifest


def verify_recovery_point(
    root: Path,
    manifest_or_path: Mapping[str, object] | Path,
) -> dict[str, object]:
    """重算文件摘要并检查业务、对象、模型、审批和复核引用闭包。"""

    root = root.resolve()
    manifest = (
        _load_json(manifest_or_path)
        if isinstance(manifest_or_path, Path)
        else dict(manifest_or_path)
    )
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise RecoveryError("恢复点模式版本不兼容")
    components = manifest.get("components")
    if not isinstance(components, dict):
        raise RecoveryError("恢复点组件结构无效")
    if set(components) != REQUIRED_COMPONENTS:
        missing = sorted(REQUIRED_COMPONENTS - set(components))
        extra = sorted(set(components) - REQUIRED_COMPONENTS)
        raise RecoveryError(f"恢复点组件不闭合，缺少={missing}，多余={extra}")

    paths: set[str] = set()
    total_size = 0
    total_files = 0
    for component, raw_entries in components.items():
        if not isinstance(raw_entries, list) or not raw_entries:
            raise RecoveryError(f"恢复点组件为空：{component}")
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise RecoveryError(f"恢复点文件项无效：{component}")
            relative = _safe_relative(str(raw_entry.get("path", "")))
            if relative in paths:
                raise RecoveryError(f"恢复点文件重复：{relative}")
            if not relative.startswith(f"{component}/"):
                raise RecoveryError(f"恢复点文件越过组件边界：{relative}")
            path = (root / relative).resolve()
            try:
                path.relative_to(root)
            except ValueError as error:
                raise RecoveryError(f"恢复点路径越界：{relative}") from error
            if not path.is_file() or path.is_symlink():
                raise RecoveryError(f"恢复点文件缺失或为符号链接：{relative}")
            expected_size = raw_entry.get("size_bytes")
            expected_hash = str(raw_entry.get("sha256", ""))
            if path.stat().st_size != expected_size or _sha256(path) != expected_hash:
                raise RecoveryError(f"恢复点文件大小或哈希不一致：{relative}")
            paths.add(relative)
            total_size += path.stat().st_size
            total_files += 1

    closure = manifest.get("reference_closure")
    if not isinstance(closure, list) or not closure:
        raise RecoveryError("恢复点没有引用闭包")
    missing_references = sorted(str(item) for item in closure if item not in paths)
    if missing_references:
        raise RecoveryError(f"恢复点引用缺失：{missing_references}")
    control_totals = manifest.get("control_totals")
    _validate_control_totals(control_totals)
    assert isinstance(control_totals, dict)
    current_model = str(control_totals["current_model"])
    if current_model not in paths or not current_model.startswith("models/"):
        raise RecoveryError("当前模型未包含在模型恢复组件中")
    for count_key, component in (
        ("object_count", "objects"),
        ("approval_count", "approvals"),
        ("review_count", "reviews"),
    ):
        raw_entries = components[component]
        assert isinstance(raw_entries, list)
        if control_totals[count_key] != len(raw_entries):
            raise RecoveryError(f"恢复控制总数与组件不一致：{count_key}")
    return {
        "status": "VERIFIED",
        "file_count": total_files,
        "size_bytes": total_size,
        "reference_count": len(closure),
    }


def restore_recovery_point(
    source_root: Path,
    manifest_path: Path,
    destination_root: Path,
    report_path: Path,
) -> dict[str, object]:
    """只向空隔离目录恢复，复制后重新验证并形成不可混淆的演练报告。"""

    source_root = source_root.resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    if any(destination_root.iterdir()):
        raise RecoveryError("恢复目标必须是空的隔离目录")
    manifest = _load_json(manifest_path)
    source_result = verify_recovery_point(source_root, manifest)
    components = manifest["components"]
    assert isinstance(components, dict)
    for raw_entries in components.values():
        assert isinstance(raw_entries, list)
        for raw_entry in raw_entries:
            assert isinstance(raw_entry, dict)
            relative = _safe_relative(str(raw_entry["path"]))
            destination = destination_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_root / relative, destination)

    restored_result = verify_recovery_point(destination_root, manifest)
    report: dict[str, object] = {
        "schema_version": "tool-defect-recovery-drill/v1",
        "status": "RESTORED_AND_VERIFIED",
        "recovery_point_id": manifest["recovery_point_id"],
        "source_verification": source_result,
        "restored_verification": restored_result,
        "control_totals": manifest["control_totals"],
        "isolated_destination": True,
        "backup_success_treated_as_restore_success": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _validate_evidence(evidence: object) -> None:
    if not isinstance(evidence, dict):
        raise RecoveryError("恢复证据必须是对象")
    _validate_control_totals(evidence.get("control_totals"))
    closure = evidence.get("reference_closure")
    if not isinstance(closure, list) or not closure:
        raise RecoveryError("恢复证据必须列出引用闭包")
    for item in closure:
        _safe_relative(str(item))


def _validate_control_totals(value: object) -> None:
    if not isinstance(value, dict):
        raise RecoveryError("恢复点缺少控制总数")
    required_positive = (
        "business_record_count",
        "object_count",
        "approval_count",
        "review_count",
    )
    for key in required_positive:
        item = value.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            raise RecoveryError(f"恢复控制总数无效：{key}")
    current_model = value.get("current_model")
    if not isinstance(current_model, str) or not current_model:
        raise RecoveryError("恢复控制总数缺少当前模型")


def _safe_relative(value: str) -> str:
    if not value or "\\" in value:
        raise RecoveryError(f"无效相对路径：{value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise RecoveryError(f"无效相对路径：{value!r}")
    return path.as_posix()


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"无效时间：{value}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"时间必须包含时区：{value}")
    return parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryError(f"无法读取恢复证据：{path}：{error}") from error


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capacity = subparsers.add_parser("capacity")
    capacity.add_argument("input", type=Path)
    capacity.add_argument("output", type=Path)

    lifecycle = subparsers.add_parser("lifecycle-plan")
    lifecycle.add_argument("input", type=Path)
    lifecycle.add_argument("output", type=Path)
    lifecycle.add_argument("--now", required=True)
    lifecycle.add_argument("--archive-days", type=int, required=True)
    lifecycle.add_argument("--cleanup-days", type=int, required=True)
    lifecycle.add_argument("--orphan-audit-days", type=int, required=True)

    create = subparsers.add_parser("create")
    create.add_argument("source", type=Path)
    create.add_argument("manifest", type=Path)
    create.add_argument("--id", required=True)
    create.add_argument("--created-at", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("root", type=Path)
    verify.add_argument("manifest", type=Path)

    restore = subparsers.add_parser("restore")
    restore.add_argument("source", type=Path)
    restore.add_argument("manifest", type=Path)
    restore.add_argument("destination", type=Path)
    restore.add_argument("report", type=Path)

    arguments = parser.parse_args()
    if arguments.command == "capacity":
        payload = _load_json(arguments.input)
        if not isinstance(payload, dict):
            raise ValueError("容量输入必须是对象")
        _write_json(arguments.output, calculate_capacity(CapacityInput(**payload)))
    elif arguments.command == "lifecycle-plan":
        payload = _load_json(arguments.input)
        if not isinstance(payload, list):
            raise ValueError("生命周期输入必须是数组")
        result = plan_lifecycle(
            payload,
            now=_parse_time(arguments.now),
            archive_after_days=arguments.archive_days,
            cleanup_after_days=arguments.cleanup_days,
            orphan_audit_days=arguments.orphan_audit_days,
        )
        _write_json(arguments.output, result)
    elif arguments.command == "create":
        create_recovery_point(
            arguments.source,
            arguments.manifest,
            recovery_point_id=arguments.id,
            created_at=_parse_time(arguments.created_at),
        )
    elif arguments.command == "verify":
        print(
            json.dumps(
                verify_recovery_point(arguments.root, arguments.manifest),
                ensure_ascii=False,
            )
        )
    elif arguments.command == "restore":
        restore_recovery_point(
            arguments.source,
            arguments.manifest,
            arguments.destination,
            arguments.report,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
