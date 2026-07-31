#!/usr/bin/env python3
"""P6-01 严格验证入口。

该脚本只读检查迁移产物和显式提供的对象/备份证据，不上传、删除或覆盖任何
图片、掩膜、清单或受控输出。缺少真实对象注册、独立备份恢复或正式审批时，
始终返回非零并报告 BLOCKED。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
OUTPUT_ROOT = REPO_ROOT / "jobs/artifact-migrator/controlled-output"

PACKAGE_SPECS: dict[str, dict[str, Any]] = {
    "baseline-180": {"version": "1.0.0", "expected_samples": 180},
    "retrain-172": {"version": "1.0.1", "expected_samples": 172},
}

PACKAGE_FILES = (
    "approval.json",
    "checksums.sha256",
    "failure-list.json",
    "manifest.csv",
    "provenance.json",
    "report.json",
    "source-snapshot.json",
    "split-audit.json",
    "statistics.json",
)


def sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def rel_path(value: str, root: Path) -> Path | None:
    """把清单路径安全解析到 root 下；绝不接受绝对路径或目录逃逸。"""

    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return resolved


def exact_case_exists(root: Path, relative: str) -> bool:
    candidate = Path(relative)
    current = root.resolve()
    for part in candidate.parts:
        if not current.is_dir():
            return False
        names = {entry.name for entry in current.iterdir()}
        if part not in names:
            return False
        current = current / part
    return current.is_file()


def add_error(errors: list[dict[str, Any]], code: str, message: str, **context: Any) -> None:
    item: dict[str, Any] = {"code": code, "message": message}
    if context:
        item["context"] = context
    errors.append(item)


def _hash_group(rows: Iterable[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        image_hash = row.get("image_sha256", "")
        if image_hash:
            grouped[image_hash].append(row)
    return grouped


def _family_group(rows: Iterable[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row.get("family_key", "")].append(row)
    return grouped


def _cross_split_count(groups: dict[str, list[dict[str, str]]]) -> int:
    return sum(
        1
        for rows in groups.values()
        if len({row.get("split", "") for row in rows}) > 1
    )


def _parse_checksums(path: Path, errors: list[dict[str, Any]]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        add_error(errors, "CHECKSUM_FILE_UNREADABLE", "无法读取 checksums.sha256", error=str(exc))
        return parsed
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            add_error(errors, "CHECKSUM_LINE_INVALID", "校验和行格式无效", line=line_number)
            continue
        digest, filename = parts
        if filename in parsed and parsed[filename] != digest:
            add_error(errors, "CHECKSUM_COLLISION", "同一文件出现不同校验和", filename=filename)
        parsed[filename] = digest
    return parsed


def _verify_package(package_name: str, package_dir: Path, errors: list[dict[str, Any]]) -> dict[str, Any]:
    spec = PACKAGE_SPECS[package_name]
    package_errors: list[dict[str, Any]] = []
    if not package_dir.is_dir():
        add_error(package_errors, "PACKAGE_MISSING", "数据集版本目录不存在", path=str(package_dir))
        errors.extend({"package": package_name, **item} for item in package_errors)
        return {"status": "BLOCKED", "sample_count": 0, "errors": package_errors}

    loaded: dict[str, Any] = {}
    for filename in PACKAGE_FILES:
        path = package_dir / filename
        if not path.is_file():
            add_error(package_errors, "PACKAGE_FILE_MISSING", "数据集版本缺少必要证据", file=filename)
            continue
        if filename.endswith(".json"):
            try:
                loaded[filename] = load_json(path)
            except (OSError, json.JSONDecodeError) as exc:
                add_error(package_errors, "PACKAGE_JSON_INVALID", "数据集版本 JSON 无法读取", file=filename, error=str(exc))

    rows: list[dict[str, str]] = []
    manifest_path = package_dir / "manifest.csv"
    if manifest_path.is_file():
        try:
            with manifest_path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                rows = list(reader)
                required_columns = {
                    "sample_id",
                    "image_path",
                    "mask_path",
                    "label",
                    "label_name",
                    "split",
                    "image_sha256",
                    "image_size_bytes",
                    "mask_sha256",
                    "mask_size_bytes",
                    "family_key",
                }
                missing_columns = required_columns - set(reader.fieldnames or [])
                if missing_columns:
                    add_error(
                        package_errors,
                        "MANIFEST_COLUMNS_MISSING",
                        "清单缺少不可变校验字段",
                        columns=sorted(missing_columns),
                    )
        except (OSError, csv.Error) as exc:
            add_error(package_errors, "MANIFEST_UNREADABLE", "清单无法读取", error=str(exc))

    if len(rows) != spec["expected_samples"]:
        add_error(
            package_errors,
            "SAMPLE_COUNT_MISMATCH",
            "清单样本数与版本契约不一致",
            actual=len(rows),
            expected=spec["expected_samples"],
        )

    source_snapshot = loaded.get("source-snapshot.json")
    snapshot_records = {
        item.get("path"): item
        for item in (source_snapshot or {}).get("objects", [])
        if isinstance(item, dict) and item.get("path")
    }
    if not snapshot_records:
        add_error(package_errors, "SOURCE_SNAPSHOT_MISSING", "缺少原目录只读快照")

    expected_checksum_entries: dict[str, str] = {}
    for row_number, row in enumerate(rows, start=2):
        for field_name in ("image_path", "mask_path"):
            relative = row.get(field_name, "")
            source_path = rel_path(relative, DATA_ROOT)
            if source_path is None:
                add_error(package_errors, "SOURCE_PATH_UNSAFE", "清单包含越界或绝对源路径", row=row_number, field=field_name)
                continue
            if not source_path.is_file():
                add_error(package_errors, "SOURCE_OBJECT_MISSING", "清单引用的源对象不存在", row=row_number, path=relative)
                continue
            if not exact_case_exists(DATA_ROOT, relative):
                add_error(
                    package_errors,
                    "SOURCE_PATH_CASE_MISMATCH",
                    "源路径大小写与真实目录不一致，不能保证跨平台复现",
                    row=row_number,
                    path=relative,
                )
            actual_size = source_path.stat().st_size
            actual_hash = sha256_hex(source_path)
            hash_field = "image_sha256" if field_name == "image_path" else "mask_sha256"
            size_field = "image_size_bytes" if field_name == "image_path" else "mask_size_bytes"
            if row.get(hash_field) != actual_hash:
                add_error(
                    package_errors,
                    "SOURCE_HASH_MISMATCH",
                    "源对象 SHA-256 与清单不一致",
                    row=row_number,
                    path=relative,
                )
            try:
                expected_size = int(row.get(size_field, "-1"))
            except ValueError:
                expected_size = -1
            if expected_size != actual_size:
                add_error(
                    package_errors,
                    "SOURCE_SIZE_MISMATCH",
                    "源对象大小与清单不一致",
                    row=row_number,
                    path=relative,
                    expected=expected_size,
                    actual=actual_size,
                )
            snapshot_item = snapshot_records.get(relative)
            if snapshot_records:
                if not snapshot_item:
                    add_error(package_errors, "SOURCE_SNAPSHOT_ENTRY_MISSING", "原目录快照缺少清单对象", path=relative)
                elif snapshot_item.get("sha256") != actual_hash or snapshot_item.get("size_bytes") != actual_size:
                    add_error(package_errors, "SOURCE_CHANGED_AFTER_SNAPSHOT", "原目录对象已偏离只读快照", path=relative)
            expected_checksum_entries[relative] = actual_hash

    checksums_path = package_dir / "checksums.sha256"
    if checksums_path.is_file():
        actual_checksum_entries = _parse_checksums(checksums_path, package_errors)
        if actual_checksum_entries != expected_checksum_entries:
            add_error(package_errors, "CHECKSUMS_NOT_RECONCILED", "对象清单与 checksums.sha256 不一致")

    hash_groups = _hash_group(rows)
    family_groups = _family_group(rows)
    cross_split_hashes = _cross_split_count(hash_groups)
    cross_split_families = _cross_split_count(family_groups)
    label_mask_issues = 0
    for row in rows:
        mask_has_content = row.get("mask_has_content", "")
        if row.get("label") == "0" and mask_has_content.lower() == "true":
            label_mask_issues += 1
        if row.get("label") == "1" and mask_has_content.lower() == "false":
            label_mask_issues += 1

    report = loaded.get("report.json")
    if not isinstance(report, dict):
        add_error(package_errors, "REPORT_MISSING", "缺少可解析的版本报告")
        report = {}
    report_counts = {
        "cross_split_issues": cross_split_hashes,
        "family_leak_issues": cross_split_families,
        "label_consistency_issues": label_mask_issues,
    }
    for field_name, expected in report_counts.items():
        if report.get(field_name) != expected:
            add_error(
                package_errors,
                "REPORT_COUNT_MISMATCH",
                "报告中的审计计数与逐行重算不一致",
                field=field_name,
                expected=expected,
                actual=report.get(field_name),
            )
    audit_blocked = bool(
        report_counts["cross_split_issues"]
        or report_counts["family_leak_issues"]
        or report_counts["label_consistency_issues"]
        or report.get("file_errors", 0)
    )
    expected_status = "BLOCKED" if audit_blocked else "COMPLETE"
    if report.get("status") != expected_status:
        add_error(
            package_errors,
            "REPORT_STATUS_UNSAFE",
            "报告状态没有反映审计失败",
            expected=expected_status,
            actual=report.get("status"),
        )
    if report.get("package_version") != spec["version"]:
        add_error(package_errors, "PACKAGE_VERSION_MISMATCH", "数据集版本号不符合冻结契约", expected=spec["version"])

    provenance = loaded.get("provenance.json")
    if not isinstance(provenance, dict) or provenance.get("package_version") != spec["version"]:
        add_error(package_errors, "PROVENANCE_INVALID", "来源记录缺少冻结版本信息")
    if isinstance(provenance, dict) and provenance.get("production_claim_allowed") is not False:
        add_error(package_errors, "HISTORICAL_RELEASE_FLAG", "历史导入不能开启生产声明")

    approval = loaded.get("approval.json")
    if not isinstance(approval, dict):
        add_error(package_errors, "APPROVAL_MISSING", "缺少审批记录")
    elif approval.get("state") not in {"DRAFT", "APPROVED"}:
        add_error(package_errors, "APPROVAL_STATE_INVALID", "审批状态未知，必须安全失败", state=approval.get("state"))

    package_status = "COMPLETE" if not package_errors else "BLOCKED"
    errors.extend({"package": package_name, **item} for item in package_errors)
    visible_package_errors = package_errors[:50]
    return {
        "status": package_status,
        "sample_count": len(rows),
        "expected_samples": spec["expected_samples"],
        "audit_status": report.get("status", "BLOCKED"),
        "error_count": len(package_errors),
        "errors": visible_package_errors,
        "errors_truncated": len(package_errors) > len(visible_package_errors),
    }


def _distinct_root(path: Path, forbidden: Iterable[Path]) -> bool:
    resolved = path.resolve()
    for item in forbidden:
        other = item.resolve()
        if resolved == other or resolved in other.parents or other in resolved.parents:
            return False
    return True


def _verify_object_registry(output_root: Path, errors: list[dict[str, Any]]) -> dict[str, Any]:
    path = output_root / "object-registry.json"
    if not path.is_file():
        add_error(errors, "OBJECT_REGISTRY_MISSING", "缺少不可变对象注册证据", file=str(path))
        return {"status": "BLOCKED", "object_count": 0}
    try:
        registry = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        add_error(errors, "OBJECT_REGISTRY_INVALID", "对象注册证据无法读取", error=str(exc))
        return {"status": "BLOCKED", "object_count": 0}
    if registry.get("status") != "COMPLETE":
        add_error(errors, "OBJECT_REGISTRY_NOT_COMPLETE", "对象注册未完成，不能放行", status=registry.get("status"))
    if registry.get("production_claim_allowed") is not False:
        add_error(errors, "OBJECT_REGISTRY_PRODUCTION_FLAG", "历史对象注册不能允许生产声明")
    object_root_value = registry.get("object_root")
    if not isinstance(object_root_value, str) or not object_root_value:
        add_error(errors, "OBJECT_ROOT_MISSING", "对象注册没有独立对象根目录")
        return {"status": "BLOCKED", "object_count": 0}
    object_root = Path(object_root_value).expanduser()
    if not object_root.is_dir():
        add_error(errors, "OBJECT_ROOT_UNAVAILABLE", "对象根目录不存在或不可读", path=str(object_root))
        return {"status": "BLOCKED", "object_count": 0}
    if not _distinct_root(object_root, (DATA_ROOT, output_root)):
        add_error(errors, "OBJECT_ROOT_NOT_ISOLATED", "对象根目录不能与源目录或受控输出复用")

    objects = registry.get("objects")
    if not isinstance(objects, list) or not objects:
        add_error(errors, "OBJECT_LIST_MISSING", "对象注册没有对象条目")
        return {"status": "BLOCKED", "object_count": 0}
    seen_keys: set[str] = set()
    actual_count = 0
    for item in objects:
        if not isinstance(item, dict):
            add_error(errors, "OBJECT_ENTRY_INVALID", "对象注册条目不是对象")
            continue
        key = item.get("object_key")
        if not isinstance(key, str) or not key or Path(key).is_absolute() or ".." in Path(key).parts:
            add_error(errors, "OBJECT_KEY_UNSAFE", "对象键为空、绝对路径或越界", key=key)
            continue
        if key in seen_keys:
            add_error(errors, "OBJECT_KEY_COLLISION", "对象键重复", key=key)
        seen_keys.add(key)
        if item.get("immutable") is not True:
            add_error(errors, "OBJECT_NOT_IMMUTABLE", "注册对象没有不可变标志", key=key)
        expected_hash = item.get("sha256")
        expected_size = item.get("size_bytes")
        object_path = (object_root / key).resolve()
        try:
            object_path.relative_to(object_root.resolve())
        except ValueError:
            add_error(errors, "OBJECT_KEY_ESCAPES_ROOT", "对象键逃逸对象根目录", key=key)
            continue
        if not object_path.is_file():
            add_error(errors, "OBJECT_MISSING", "注册对象不存在", key=key)
            continue
        actual_count += 1
        if object_path.stat().st_size != expected_size or sha256_hex(object_path) != expected_hash:
            add_error(errors, "OBJECT_HASH_MISMATCH", "对象大小或 SHA-256 不一致", key=key)
    if registry.get("object_count") != len(objects):
        add_error(errors, "OBJECT_COUNT_MISMATCH", "注册汇总对象数不一致")
    return {
        "status": "COMPLETE" if not any(item.get("code", "").startswith("OBJECT_") for item in errors) and registry.get("status") == "COMPLETE" else "BLOCKED",
        "object_count": len(objects),
        "available_count": actual_count,
        "registry_sha256": sha256_hex(path),
        "registry": registry,
    }


def _verify_backup_and_rollback(
    output_root: Path,
    object_result: dict[str, Any],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence_path = output_root / "backup-verification.json"
    if not evidence_path.is_file():
        add_error(errors, "BACKUP_EVIDENCE_MISSING", "缺少备份与回滚验证证据")
        return {"status": "BLOCKED"}
    try:
        evidence = load_json(evidence_path)
    except (OSError, json.JSONDecodeError) as exc:
        add_error(errors, "BACKUP_EVIDENCE_INVALID", "备份与回滚证据无法读取", error=str(exc))
        return {"status": "BLOCKED"}
    if evidence.get("status") != "COMPLETE":
        add_error(errors, "BACKUP_NOT_COMPLETE", "备份或回滚验证未完成", status=evidence.get("status"))
    if evidence.get("registry_sha256") != object_result.get("registry_sha256"):
        add_error(errors, "BACKUP_REGISTRY_MISMATCH", "备份证据未绑定当前对象注册版本")
    backup_root_value = evidence.get("backup_root")
    restore_root_value = evidence.get("restore_root")
    if not isinstance(backup_root_value, str) or not isinstance(restore_root_value, str):
        add_error(errors, "BACKUP_ROOT_MISSING", "备份或恢复根目录缺失")
        return {"status": "BLOCKED"}
    backup_root = Path(backup_root_value).expanduser()
    restore_root = Path(restore_root_value).expanduser()
    if not backup_root.is_dir() or not restore_root.is_dir():
        add_error(errors, "BACKUP_ROOT_UNAVAILABLE", "备份或恢复根目录不存在")
        return {"status": "BLOCKED"}
    object_root_value = (object_result.get("registry") or {}).get("object_root")
    roots = [Path(value).expanduser() for value in (object_root_value, backup_root_value, restore_root_value) if isinstance(value, str)]
    if len({root.resolve() for root in roots}) != 3 or any(
        not _distinct_root(root, tuple(other for other in roots if other != root))
        for root in roots
    ):
        add_error(errors, "BACKUP_ROOT_NOT_ISOLATED", "对象、备份和恢复根目录必须彼此独立")
    objects = (object_result.get("registry") or {}).get("objects", [])
    checked = 0
    for item in objects:
        if not isinstance(item, dict):
            continue
        key = item.get("object_key")
        if not isinstance(key, str):
            continue
        for label, root in (("backup", backup_root), ("restore", restore_root)):
            candidate = (root / key).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                add_error(errors, "BACKUP_KEY_ESCAPES_ROOT", "备份对象键逃逸根目录", key=key, root=label)
                continue
            if not candidate.is_file():
                add_error(errors, "BACKUP_OBJECT_MISSING", "备份或恢复对象缺失", key=key, root=label)
                continue
            checked += 1
            if candidate.stat().st_size != item.get("size_bytes") or sha256_hex(candidate) != item.get("sha256"):
                add_error(errors, "BACKUP_OBJECT_HASH_MISMATCH", "备份或恢复对象哈希不一致", key=key, root=label)
    return {
        "status": "COMPLETE" if evidence.get("status") == "COMPLETE" and checked == len(objects) * 2 and not any(item.get("code", "").startswith("BACKUP_") for item in errors) else "BLOCKED",
        "checked_objects": checked,
        "expected_objects": len(objects) * 2,
    }


def verify_p6_01(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    output_root = output_root.resolve()
    errors: list[dict[str, Any]] = []
    package_results: dict[str, Any] = {}
    for package_name in PACKAGE_SPECS:
        package_results[package_name] = _verify_package(package_name, output_root / package_name, errors)
        if package_results[package_name].get("audit_status") != "COMPLETE":
            add_error(
                errors,
                "PACKAGE_AUDIT_BLOCKED",
                "任一历史版本审计阻断时，P6-01 不能通过",
                package=package_name,
                status=package_results[package_name].get("audit_status"),
            )

    summary_path = output_root / "summary.json"
    summary: dict[str, Any] = {}
    if not summary_path.is_file():
        add_error(errors, "SUMMARY_MISSING", "缺少迁移总汇总")
    else:
        try:
            summary = load_json(summary_path)
        except (OSError, json.JSONDecodeError) as exc:
            add_error(errors, "SUMMARY_INVALID", "迁移总汇总无法读取", error=str(exc))
    if summary.get("production_claim_allowed") is not False:
        add_error(errors, "SUMMARY_PRODUCTION_FLAG", "迁移总汇总不能允许生产声明")
    if summary.get("migrator_version") != "1.0.0":
        add_error(errors, "MIGRATOR_VERSION_MISMATCH", "迁移器版本未锁定", expected="1.0.0")
    expected_overall = "COMPLETE" if all(result.get("audit_status") == "COMPLETE" for result in package_results.values()) else "BLOCKED"
    if summary.get("overall_status") != expected_overall:
        add_error(errors, "SUMMARY_STATUS_MISMATCH", "总汇总状态与版本审计不一致", expected=expected_overall, actual=summary.get("overall_status"))

    object_result = _verify_object_registry(output_root, errors)
    backup_result = _verify_backup_and_rollback(output_root, object_result, errors)

    formal_approval = True
    for package_name in PACKAGE_SPECS:
        approval_path = output_root / package_name / "approval.json"
        try:
            approval = load_json(approval_path)
        except (OSError, json.JSONDecodeError):
            formal_approval = False
            continue
        if approval.get("state") != "APPROVED":
            formal_approval = False
            add_error(errors, "FORMAL_APPROVAL_MISSING", "两套历史版本均需独立正式审批", package=package_name)
        if not approval.get("approved_by") or approval.get("generated_by") == "artifact-migrator":
            formal_approval = False
            add_error(errors, "APPROVAL_NOT_INDEPENDENT", "审批人必须独立于迁移器")

    status = "COMPLETE" if not errors and formal_approval else "BLOCKED"
    visible_errors = errors[:100]
    return {
       "schema_version": "p6-01-verification.v1",
       "status": status,
       "production_claim_allowed": False,
       "output_root": str(output_root),
       "packages": package_results,
       "object_registration": {
           "status": object_result.get("status", "BLOCKED"),
           "object_count": object_result.get("object_count", 0),
           "available_count": object_result.get("available_count", 0),
       },
       "backup_and_rollback": backup_result,
       "formal_approval": formal_approval,
       "error_count": len(errors),
        "errors": visible_errors,
        "errors_truncated": len(errors) > len(visible_errors),
   }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读验证 P6-01 历史数据导入与不可变基线")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    try:
        result = verify_p6_01(args.output_root)
    except Exception as exc:  # 安全失败：验证器自身异常也不能变成通过
        result = {
            "schema_version": "p6-01-verification.v1",
            "status": "BLOCKED",
            "production_claim_allowed": False,
            "error_count": 1,
            "errors": [{"code": "VERIFIER_EXCEPTION", "message": str(exc), "type": type(exc).__name__}],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status") == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
