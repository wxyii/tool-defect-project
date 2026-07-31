#!/usr/bin/env python3
"""在外部对象存储挂载目录上登记 P6-01 对象并验证备份/恢复。

该命令不负责上传、复制、删除或覆盖对象。对象必须先由受控迁移流程放入
独立根目录；本命令只按不可变键重算大小和 SHA-256，并写入小型机器可读证据。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
DEFAULT_OUTPUT = REPO_ROOT / "jobs/artifact-migrator/controlled-output"
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


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def safe_key(*parts: str) -> str:
    values = [part.replace("\\", "/").strip("/") for part in parts]
    if any(not part or part == "." or ".." in Path(part).parts for part in values):
        raise ValueError(f"对象键包含非法路径段：{parts}")
    return "/".join(values)


def isolated(root: Path, *other_roots: Path) -> bool:
    resolved = root.resolve()
    return all(
        resolved != other.resolve()
        and resolved not in other.resolve().parents
        and other.resolve() not in resolved.parents
        for other in other_roots
    )


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def source_file_for(relative_path: str) -> Path | None:
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts or not relative_path:
        return None
    resolved = (DATA_ROOT / candidate).resolve()
    try:
        resolved.relative_to(DATA_ROOT.resolve())
    except ValueError:
        return None
    return resolved


def object_entry(
    *,
    object_key: str,
    expected_sha256: str,
    expected_size: int,
    package_name: str,
    package_version: str,
    kind: str,
    source_path: str,
) -> dict[str, Any]:
    return {
        "object_key": object_key,
        "sha256": expected_sha256,
        "size_bytes": expected_size,
        "package_name": package_name,
        "package_version": package_version,
        "kind": kind,
        "source_path": source_path,
        "immutable": True,
    }


def collect_expected_objects(output_root: Path, errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    objects: dict[str, dict[str, Any]] = {}
    for package_name in ("baseline-180", "retrain-172"):
        package_dir = output_root / package_name
        provenance_path = package_dir / "provenance.json"
        manifest_path = package_dir / "manifest.csv"
        if not provenance_path.is_file() or not manifest_path.is_file():
            errors.append({"code": "PACKAGE_EVIDENCE_MISSING", "package": package_name})
            continue
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append({"code": "PROVENANCE_INVALID", "package": package_name, "message": str(exc)})
            continue
        version = provenance.get("package_version")
        if not isinstance(version, str) or not version:
            errors.append({"code": "PACKAGE_VERSION_MISSING", "package": package_name})
            continue
        prefix = safe_key("datasets", "historical-import", package_name, version)
        for filename in PACKAGE_FILES:
            path = package_dir / filename
            if not path.is_file():
                errors.append({"code": "PACKAGE_FILE_MISSING", "package": package_name, "file": filename})
                continue
            key = safe_key(prefix, "metadata", filename)
            objects[key] = object_entry(
                object_key=key,
                expected_sha256=sha256_hex(path),
                expected_size=path.stat().st_size,
                package_name=package_name,
                package_version=version,
                kind="dataset_metadata",
                source_path=display_path(path),
            )
        try:
            with manifest_path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
        except (OSError, csv.Error) as exc:
            errors.append({"code": "MANIFEST_INVALID", "package": package_name, "message": str(exc)})
            continue
        for row in rows:
            for field_name, hash_field, size_field, kind in (
                ("image_path", "image_sha256", "image_size_bytes", "historical_image"),
                ("mask_path", "mask_sha256", "mask_size_bytes", "historical_mask"),
            ):
                source_path = row.get(field_name, "")
                source_file = source_file_for(source_path)
                if source_file is None:
                    errors.append({"code": "SOURCE_PATH_UNSAFE", "package": package_name, "path": source_path})
                    continue
                if not source_file.is_file():
                    errors.append({"code": "SOURCE_OBJECT_MISSING", "package": package_name, "path": source_path})
                    continue
                try:
                    expected_size = int(row.get(size_field, "-1"))
                except ValueError:
                    expected_size = -1
                expected_hash = row.get(hash_field, "")
                actual_size = source_file.stat().st_size
                actual_hash = sha256_hex(source_file)
                if expected_size != actual_size or expected_hash != actual_hash:
                    errors.append({"code": "SOURCE_MANIFEST_MISMATCH", "package": package_name, "path": source_path})
                if not expected_hash:
                    errors.append({"code": "SOURCE_HASH_MISSING", "package": package_name, "path": source_path})
                    continue
                key = safe_key(prefix, "objects", kind, expected_hash)
                entry = object_entry(
                    object_key=key,
                    expected_sha256=expected_hash,
                    expected_size=expected_size,
                    package_name=package_name,
                    package_version=version,
                    kind=kind,
                    source_path=source_path,
                )
                existing = objects.get(key)
                if existing is None:
                    objects[key] = entry
                elif (
                    existing.get("sha256") != entry.get("sha256")
                    or existing.get("size_bytes") != entry.get("size_bytes")
                    or existing.get("package_name") != entry.get("package_name")
                    or existing.get("package_version") != entry.get("package_version")
                    or existing.get("kind") != entry.get("kind")
                ):
                    errors.append({"code": "OBJECT_KEY_COLLISION", "key": key})
                else:
                    source_paths = existing.setdefault("source_paths", [existing.get("source_path")])
                    if source_path not in source_paths:
                        source_paths.append(source_path)
    return [objects[key] for key in sorted(objects)]


def check_root_objects(root: Path, objects: list[dict[str, Any]], errors: list[dict[str, Any]], label: str) -> int:
    available = 0
    for item in objects:
        key = item["object_key"]
        candidate = (root / key).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            errors.append({"code": "OBJECT_KEY_ESCAPES_ROOT", "root": label, "key": key})
            continue
        if not candidate.is_file():
            errors.append({"code": "OBJECT_MISSING", "root": label, "key": key})
            continue
        available += 1
        actual_size = candidate.stat().st_size
        actual_hash = sha256_hex(candidate)
        if actual_size != item["size_bytes"] or actual_hash != item["sha256"]:
            errors.append({"code": "OBJECT_HASH_MISMATCH", "root": label, "key": key})
    return available


def register(
    output_root: Path,
    object_root: Path,
    backup_root: Path,
    restore_root: Path,
) -> int:
    output_root = output_root.resolve()
    object_root = object_root.expanduser().resolve()
    backup_root = backup_root.expanduser().resolve()
    restore_root = restore_root.expanduser().resolve()
    errors: list[dict[str, Any]] = []
    if not object_root.is_dir() or not backup_root.is_dir() or not restore_root.is_dir():
        errors.append({"code": "ROOT_UNAVAILABLE", "message": "对象、备份和恢复根目录必须已存在且为目录"})
    if not isolated(object_root, DATA_ROOT, output_root) or not isolated(backup_root, DATA_ROOT, output_root) or not isolated(restore_root, DATA_ROOT, output_root):
        errors.append({"code": "ROOT_NOT_ISOLATED", "message": "对象/备份/恢复根目录不能复用源目录或受控输出"})
    if len({object_root, backup_root, restore_root}) != 3:
        errors.append({"code": "ROOT_COLLISION", "message": "对象、备份和恢复根目录必须彼此独立"})

    objects = collect_expected_objects(output_root, errors)
    available = check_root_objects(object_root, objects, errors, "object") if object_root.is_dir() else 0
    registry = {
        "schema_version": "p6-01-object-registry.v1",
        "status": "COMPLETE" if not errors and available == len(objects) else "BLOCKED",
        "registry_mode": "external-mounted-root",
        "object_root": str(object_root),
        "object_count": len(objects),
        "available_count": available,
        "packages": sorted({item["package_name"] for item in objects}),
        "objects": objects,
        "production_claim_allowed": False,
        "errors": errors,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    registry_path = output_root / "object-registry.json"
    write_json(registry_path, registry)
    registry_sha256 = sha256_hex(registry_path)

    backup_errors = list(errors)
    backup_available = check_root_objects(backup_root, objects, backup_errors, "backup") if backup_root.is_dir() else 0
    restore_available = check_root_objects(restore_root, objects, backup_errors, "restore") if restore_root.is_dir() else 0
    backup_status = "COMPLETE" if not backup_errors and backup_available == len(objects) and restore_available == len(objects) else "BLOCKED"
    backup_evidence = {
        "schema_version": "p6-01-backup-verification.v1",
        "status": backup_status,
        "object_root": str(object_root),
        "backup_root": str(backup_root),
        "restore_root": str(restore_root),
        "registry_sha256": registry_sha256,
        "object_count": len(objects),
        "backup_available_count": backup_available,
        "restore_available_count": restore_available,
        "errors": backup_errors,
        "production_claim_allowed": False,
    }
    write_json(output_root / "backup-verification.json", backup_evidence)
    print(json.dumps({
        "registry": {
            "status": registry["status"],
            "object_count": registry["object_count"],
            "available_count": registry["available_count"],
            "error_count": len(registry["errors"]),
        },
        "backup_verification": {
            "status": backup_evidence["status"],
            "object_count": backup_evidence["object_count"],
            "backup_available_count": backup_evidence["backup_available_count"],
            "restore_available_count": backup_evidence["restore_available_count"],
            "error_count": len(backup_evidence["errors"]),
        },
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if registry["status"] == "COMPLETE" and backup_status == "COMPLETE" else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="登记并验证 P6-01 外部对象/备份/恢复根目录")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--object-root", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--restore-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return register(args.output_root, args.object_root, args.backup_root, args.restore_root)
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
