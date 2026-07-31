#!/usr/bin/env python3
"""P6-02 受控数据集版本的严格、只读验证器。

该验证器不把构建报告视为事实，而是重新读取最终清单、解码图像/掩膜并复算哈希。
缺少正式质量审批、来源证据或任一完整性前置条件时必须返回非零。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from curation import (
    APPROXIMATE_HASH_DISTANCE,
    DATA_DIR,
    DEFAULT_OUTPUT_DIR,
    Image,
    hamming_distance,
    perceptual_hash,
    safe_data_path,
    sha256_file,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION_NAME = "production-candidate-v1"
REQUIRED_FILES = {
    "approval.json",
    "checksums.sha256",
    "diff-report.json",
    "manifest.csv",
    "provenance.json",
    "quarantine.json",
    "report.json",
    "split-audit.json",
    "statistics.json",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _load_json(path: Path, errors: List[str]) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{path.name}:json_{type(exc).__name__}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.name}:root_not_object")
        return {}
    return value


def _relative_or_absolute(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _parse_checksums(path: Path, errors: List[str]) -> Dict[str, str]:
    checksums: Dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        errors.append(f"checksums.sha256:read_{type(exc).__name__}")
        return checksums
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or not SHA256_RE.fullmatch(parts[0]):
            errors.append(f"checksums.sha256:line_{line_number}_invalid")
            continue
        digest, relative_path = parts
        relative_path = relative_path.lstrip("*")
        if relative_path in checksums and checksums[relative_path] != digest:
            errors.append(f"checksums.sha256:hash_collision:{relative_path}")
        checksums[relative_path] = digest
    return checksums


def _bool_value(value: str) -> Optional[bool]:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _manifest_rows(path: Path, errors: List[str]) -> List[Dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            required = {
                "sample_key", "image_path", "mask_path", "label", "label_name", "split",
                "group_key", "content_sha256", "mask_sha256", "image_size_bytes", "mask_size_bytes",
                "image_width", "image_height", "mask_width", "mask_height", "mask_has_content",
                "source", "source_license_state", "review_state", "quality_state", "difficulty",
                "capture_id", "source_review_id",
            }
            missing = required - set(reader.fieldnames or [])
            if missing:
                errors.append(f"manifest.csv:columns_missing:{','.join(sorted(missing))}")
                return []
            return list(reader)
    except Exception as exc:
        errors.append(f"manifest.csv:read_{type(exc).__name__}")
        return []


def _verify_rows(
    rows: Iterable[Dict[str, str]],
    checksums: Dict[str, str],
    errors: List[str],
) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, Set[str]]], List[Tuple[str, str, int]]]:
    accepted = list(rows)
    seen_keys: Set[str] = set()
    image_hashes: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: {"splits": set(), "labels": set(), "keys": set()})
    groups: Dict[str, Set[str]] = defaultdict(set)
    image_hash_by_key: Dict[str, int] = {}
    image_key_by_hash: Dict[str, str] = {}
    for row in accepted:
        key = (row.get("sample_key") or "").strip()
        if not key:
            errors.append("manifest.csv:sample_key_missing")
        elif key in seen_keys:
            errors.append(f"manifest.csv:duplicate_sample_key:{key}")
        seen_keys.add(key)
        image_path_text = (row.get("image_path") or "").strip()
        mask_path_text = (row.get("mask_path") or "").strip()
        image_path = safe_data_path(image_path_text)
        mask_path = safe_data_path(mask_path_text)
        if image_path is None or not image_path.is_file():
            errors.append(f"{key}:image_missing_or_unsafe")
            continue
        if mask_path is None or not mask_path.is_file():
            errors.append(f"{key}:mask_missing_or_unsafe")
            continue
        image_digest = sha256_file(image_path)
        mask_digest = sha256_file(mask_path)
        if image_digest != row.get("content_sha256", ""):
            errors.append(f"{key}:image_hash_mismatch")
        if mask_digest != row.get("mask_sha256", ""):
            errors.append(f"{key}:mask_hash_mismatch")
        if checksums.get(image_path_text) != image_digest:
            errors.append(f"{key}:image_checksum_missing_or_mismatch")
        if checksums.get(mask_path_text) != mask_digest:
            errors.append(f"{key}:mask_checksum_missing_or_mismatch")
        if str(image_path.stat().st_size) != row.get("image_size_bytes", ""):
            errors.append(f"{key}:image_size_mismatch")
        if str(mask_path.stat().st_size) != row.get("mask_size_bytes", ""):
            errors.append(f"{key}:mask_size_mismatch")
        if Image is None:
            errors.append("Pillow_unavailable")
            continue
        try:
            with Image.open(image_path) as image:
                image_dimensions = image.size
            with Image.open(mask_path) as mask:
                mask_dimensions = mask.size
                mask_has_content = mask.convert("L").getbbox() is not None
            if image_dimensions != (int(row["image_width"]), int(row["image_height"])):
                errors.append(f"{key}:image_dimensions_mismatch")
            if mask_dimensions != (int(row["mask_width"]), int(row["mask_height"])):
                errors.append(f"{key}:mask_dimensions_mismatch")
            if mask_dimensions != image_dimensions:
                errors.append(f"{key}:image_mask_dimensions_differ")
            if _bool_value(row.get("mask_has_content", "")) is not mask_has_content:
                errors.append(f"{key}:mask_content_mismatch")
            if int(row.get("label", "-1")) == 1 and not mask_has_content:
                errors.append(f"{key}:positive_empty_mask")
            image_hash_by_key[key] = perceptual_hash(image_path) or 0
        except Exception as exc:
            errors.append(f"{key}:decode_{type(exc).__name__}")
        if row.get("source_license_state") != "APPROVED":
            errors.append(f"{key}:source_license_not_approved")
        if row.get("review_state") != "CLOSED":
            errors.append(f"{key}:review_not_closed")
        if row.get("quality_state") != "APPROVED":
            errors.append(f"{key}:quality_not_approved")
        if row.get("difficulty") not in {"NORMAL", "HARD"}:
            errors.append(f"{key}:difficulty_invalid")
        for field in ("source", "capture_id", "source_review_id", "group_key"):
            if not (row.get(field) or "").strip():
                errors.append(f"{key}:{field}_missing")
        try:
            label = int(row.get("label", "-1"))
        except ValueError:
            label = -1
        if label not in {0, 1}:
            errors.append(f"{key}:label_invalid")
        if row.get("split") not in {"train", "validation", "test"}:
            errors.append(f"{key}:split_invalid")
        image_hashes[image_digest]["splits"].add(row.get("split", ""))
        image_hashes[image_digest]["labels"].add(str(label))
        image_hashes[image_digest]["keys"].add(key)
        groups[row.get("group_key", "")].add(row.get("split", ""))
        image_key_by_hash.setdefault(image_digest, key)
    for digest, values in image_hashes.items():
        if len(values["splits"]) > 1:
            errors.append(f"cross_split_image_hash:{digest[:16]}")
        if len(values["labels"]) > 1:
            errors.append(f"conflicting_image_label:{digest[:16]}")
    for group_key, splits in groups.items():
        if len(splits) > 1:
            errors.append(f"family_cross_split:{group_key}")
    near_pairs: List[Tuple[str, str, int]] = []
    keys = sorted(image_hash_by_key)
    for index, left_key in enumerate(keys):
        for right_key in keys[index + 1 :]:
            distance = hamming_distance(image_hash_by_key[left_key], image_hash_by_key[right_key])
            if distance <= APPROXIMATE_HASH_DISTANCE:
                near_pairs.append((left_key, right_key, distance))
                errors.append(f"approximate_duplicate:{left_key}:{right_key}:distance={distance}")
    return accepted, image_hashes, near_pairs


def verify_version(package_dir: Path) -> Dict[str, Any]:
    errors: List[str] = []
    if not package_dir.is_dir():
        return {"status": "BLOCKED", "errors": [f"missing_package:{package_dir}"]}
    missing_files = sorted(name for name in REQUIRED_FILES if not (package_dir / name).is_file())
    if missing_files:
        errors.extend(f"missing_file:{name}" for name in missing_files)
    if errors:
        return {"status": "BLOCKED", "errors": errors}

    approval = _load_json(package_dir / "approval.json", errors)
    diff_report = _load_json(package_dir / "diff-report.json", errors)
    provenance = _load_json(package_dir / "provenance.json", errors)
    quarantine = _load_json(package_dir / "quarantine.json", errors)
    report = _load_json(package_dir / "report.json", errors)
    audit = _load_json(package_dir / "split-audit.json", errors)
    statistics = _load_json(package_dir / "statistics.json", errors)
    checksums = _parse_checksums(package_dir / "checksums.sha256", errors)
    rows = _manifest_rows(package_dir / "manifest.csv", errors)

    if report.get("version_name") != VERSION_NAME:
        errors.append("report:version_name_mismatch")
    if report.get("status") != "COMPLETE":
        errors.append(f"report:status={report.get('status', 'MISSING')}")
    if report.get("blocker_count") != 0:
        errors.append(f"report:blocker_count={report.get('blocker_count')}")
    if report.get("production_claim_allowed") is not False:
        errors.append("report:production_claim_must_be_false")
    if approval.get("state") != "APPROVED":
        errors.append(f"approval:state={approval.get('state', 'MISSING')}")
    if approval.get("independent") is not True and approval.get("independent_approver") is not True:
        errors.append("approval:independent_approver_missing")
    if not (approval.get("approved_by") or "").strip():
        errors.append("approval:approved_by_missing")
    if not (approval.get("approved_at") or "").strip():
        errors.append("approval:approved_at_missing")
    if approval.get("approved_by") and approval.get("approved_by") == approval.get("generated_by"):
        errors.append("approval:self_approval")
    if provenance.get("immutable") is not True:
        errors.append("provenance:immutable_marker_missing")
    if provenance.get("production_claim_allowed") is not False:
        errors.append("provenance:production_claim_must_be_false")
    manifest_path = package_dir / "manifest.csv"
    if provenance.get("manifest_sha256") != sha256_file(manifest_path):
        errors.append("provenance:manifest_hash_mismatch")
    parent_value = provenance.get("parent_manifest")
    if not isinstance(parent_value, str) or not parent_value:
        errors.append("provenance:parent_manifest_missing")
    else:
        parent_path = _relative_or_absolute(parent_value)
        if not parent_path.is_file():
            errors.append("provenance:parent_manifest_missing_on_disk")
    if not provenance.get("candidate_manifest_sha256"):
        errors.append("provenance:candidate_manifest_hash_missing")

    rows, image_hashes, near_pairs = _verify_rows(rows, checksums, errors)
    if not rows:
        errors.append("manifest:accepted_samples_empty")
    if len(checksums) != len(rows) * 2:
        errors.append(f"checksums:expected={len(rows) * 2}:actual={len(checksums)}")
    if len(image_hashes) != len(rows):
        errors.append("manifest:duplicate_image_hashes")
    if near_pairs:
        errors.append(f"manifest:near_duplicate_pairs={len(near_pairs)}")
    expected_difficulties = {"NORMAL", "HARD"}
    actual_difficulties = {row.get("difficulty") for row in rows}
    if not expected_difficulties.issubset(actual_difficulties):
        errors.append("manifest:normal_and_hard_required")

    expected_splits: Dict[str, int] = defaultdict(int)
    expected_labels: Dict[str, int] = defaultdict(int)
    expected_difficulties_count: Dict[str, int] = defaultdict(int)
    for row in rows:
        expected_splits[row.get("split", "")] += 1
        expected_labels[row.get("label_name", "")] += 1
        expected_difficulties_count[row.get("difficulty", "")] += 1
    if statistics.get("accepted_samples") != len(rows):
        errors.append("statistics:accepted_samples_mismatch")
    if statistics.get("split_counts") != dict(expected_splits):
        errors.append("statistics:split_counts_mismatch")
    if statistics.get("label_counts") != dict(expected_labels):
        errors.append("statistics:label_counts_mismatch")
    if statistics.get("difficulty_counts") != dict(expected_difficulties_count):
        errors.append("statistics:difficulty_counts_mismatch")
    if report.get("accepted_samples") != len(rows):
        errors.append("report:accepted_samples_mismatch")
    if diff_report.get("current_sample_count") != len(rows):
        errors.append("diff_report:current_sample_count_mismatch")
    if not isinstance(diff_report.get("added_sample_keys"), list) or not isinstance(diff_report.get("removed_sample_keys"), list):
        errors.append("diff_report:version_diff_missing")
    for field in (
        "cross_split_hash_issues", "conflicting_label_issues", "family_cross_split_issues",
        "approximate_duplicate_conflicts", "metadata_issues",
    ):
        value = audit.get(field)
        if value not in ([], {}):
            errors.append(f"split_audit:{field}_not_empty")
    if audit.get("quarantined_sample_keys") is None:
        errors.append("split_audit:quarantine_list_missing")
    if quarantine.get("status") not in {"EMPTY", "QUARANTINED"}:
        errors.append(f"quarantine:status={quarantine.get('status', 'MISSING')}")
    if quarantine.get("blockers") and any(quarantine["blockers"].values()):
        errors.append("quarantine:blockers_not_empty")
    return {
        "status": "COMPLETE" if not errors else "BLOCKED",
        "version": provenance.get("version_name", VERSION_NAME),
        "accepted_samples": len(rows),
        "error_count": len(errors),
        "errors": errors[:60],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="严格验证 P6-02 不可变数据集版本")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--version", default=VERSION_NAME)
    args = parser.parse_args(argv)
    package_dir = args.output_dir.resolve() / args.version
    try:
        result = verify_version(package_dir)
    except Exception as exc:
        result = {"status": "BLOCKED", "errors": [f"verifier_exception:{type(exc).__name__}:{exc}"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
