#!/usr/bin/env python3
"""P6-02 候选样本准入、去重、划分和不可变数据集构建。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
MANIFESTS_DIR = DATA_DIR / "manifests"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "jobs" / "dataset-builder" / "controlled-output"
DEFAULT_CANDIDATE_MANIFEST = MANIFESTS_DIR / "retrain.csv"
DEFAULT_PARENT_MANIFEST = MANIFESTS_DIR / "retrain.csv"
HASH_CHUNK = 1024 * 1024
APPROXIMATE_HASH_DISTANCE = 4

try:
    from PIL import Image
except ImportError:  # 严格门禁会把解码器缺失作为阻断
    Image = None


@dataclass
class CandidateSample:
    sample_key: str
    image_path: str
    mask_path: str
    label: int
    label_name: str
    split: str
    group_key: str
    source: str
    source_license_state: str
    review_state: str
    quality_state: str
    difficulty: str
    capture_id: str
    source_review_id: str
    content_sha256: str = ""
    mask_sha256: str = ""
    image_size_bytes: int = 0
    mask_size_bytes: int = 0
    image_width: int = 0
    image_height: int = 0
    mask_width: int = 0
    mask_height: int = 0
    mask_has_content: Optional[bool] = None
    perceptual_hash: Optional[int] = None
    errors: List[str] = field(default_factory=list)


def sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        while chunk := stream.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def safe_data_path(relative_path: str) -> Optional[Path]:
    candidate = Path(relative_path)
    if not relative_path or candidate.is_absolute() or ".." in candidate.parts:
        return None
    resolved = (DATA_DIR / candidate).resolve()
    try:
        resolved.relative_to(DATA_DIR.resolve())
    except ValueError:
        return None
    current = DATA_DIR.resolve()
    for part in candidate.parts:
        if not current.is_dir():
            return None
        names = {entry.name for entry in current.iterdir()}
        if part not in names:
            # 大小写不一致在 macOS 默认文件系统上可能仍能打开；拒绝它，
            # 确保冻结清单在 Linux/容器环境中具有相同语义。
            return None
        current = current / part
    return resolved


def filename_group(sample_key: str) -> str:
    parts = sample_key.split("/")
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1].rsplit('.', 1)[0]}"
    return sample_key.rsplit(".", 1)[0]


def perceptual_hash(image_path: Path) -> Optional[int]:
    if Image is None:
        return None
    with Image.open(image_path) as image:
        gray = image.convert("L").resize((8, 8))
        values = list(gray.getdata())
    average = sum(values) / len(values)
    result = 0
    for value in values:
        result = (result << 1) | int(value >= average)
    return result


def inspect_image_and_mask(sample: CandidateSample) -> None:
    image_path = safe_data_path(sample.image_path)
    mask_path = safe_data_path(sample.mask_path)
    if image_path is None:
        sample.errors.append("image_path_unsafe")
    elif not image_path.is_file():
        sample.errors.append("image_missing")
    if mask_path is None:
        sample.errors.append("mask_path_unsafe")
    elif not mask_path.is_file():
        sample.errors.append("mask_missing")
    if image_path is None or not image_path.is_file():
        return
    sample.image_size_bytes = image_path.stat().st_size
    sample.content_sha256 = sha256_file(image_path)
    if Image is None:
        sample.errors.append("image_decoder_unavailable")
        return
    try:
        with Image.open(image_path) as image:
            sample.image_width, sample.image_height = image.size
        sample.perceptual_hash = perceptual_hash(image_path)
    except Exception as exc:
        sample.errors.append(f"image_decode:{type(exc).__name__}")
    if mask_path is None or not mask_path.is_file():
        return
    sample.mask_size_bytes = mask_path.stat().st_size
    sample.mask_sha256 = sha256_file(mask_path)
    try:
        with Image.open(mask_path) as mask:
            sample.mask_width, sample.mask_height = mask.size
            sample.mask_has_content = mask.convert("L").getbbox() is not None
    except Exception as exc:
        sample.errors.append(f"mask_decode:{type(exc).__name__}")
        return
    if (sample.image_width, sample.image_height) != (sample.mask_width, sample.mask_height):
        sample.errors.append("mask_dimensions_mismatch")
    if sample.label == 1 and sample.mask_has_content is not True:
        sample.errors.append("positive_empty_mask")


def _required_value(row: Dict[str, str], names: Iterable[str]) -> str:
    for name in names:
        value = (row.get(name) or "").strip()
        if value:
            return value
    return ""


def load_candidate_manifest(manifest_path: Path) -> Tuple[List[CandidateSample], List[str]]:
    samples: List[CandidateSample] = []
    errors: List[str] = []
    with manifest_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        fieldnames = set(reader.fieldnames or [])
        required = {"image_path", "mask_path", "label", "label_name", "split"}
        missing = required - fieldnames
        if "sample_key" not in fieldnames and "sample_id" not in fieldnames:
            missing.add("sample_key_or_sample_id")
        if missing:
            return [], [f"manifest_columns_missing:{','.join(sorted(missing))}"]
        for row_number, row in enumerate(reader, start=2):
            try:
                label = int(row.get("label", ""))
            except ValueError:
                errors.append(f"row_{row_number}:label_invalid")
                continue
            sample_key = _required_value(row, ("sample_key", "sample_id"))
            sample = CandidateSample(
                sample_key=sample_key,
                image_path=(row.get("image_path") or "").strip(),
                mask_path=(row.get("mask_path") or "").strip(),
                label=label,
                label_name=(row.get("label_name") or "").strip(),
                split=(row.get("split") or "").strip().lower(),
                group_key=(row.get("group_key") or "").strip() or filename_group(sample_key),
                source=(row.get("source") or "").strip(),
                source_license_state=_required_value(row, ("source_license_state", "license_state")),
                review_state=_required_value(row, ("review_state", "source_review_state")),
                quality_state=_required_value(row, ("quality_state", "quality_approval_state")),
                difficulty=(row.get("difficulty") or "").strip().upper(),
                capture_id=(row.get("capture_id") or "").strip(),
                source_review_id=(row.get("source_review_id") or "").strip(),
            )
            if not sample.sample_key:
                sample.errors.append("sample_key_missing")
            if sample.split not in {"train", "validation", "test"}:
                sample.errors.append("split_invalid")
            if sample.label not in {0, 1}:
                sample.errors.append("label_invalid")
            inspect_image_and_mask(sample)
            samples.append(sample)
    return samples, errors


def hamming_distance(left: int, right: int) -> int:
    # 项目源码门禁支持 Python 3.9；int.bit_count() 仅在 3.8+ 的部分环境可用，
    # 用等价的二进制计数保持锁定运行时兼容。
    return bin(left ^ right).count("1")


def exact_duplicate_groups(samples: Iterable[CandidateSample]) -> Dict[str, List[CandidateSample]]:
    groups: Dict[str, List[CandidateSample]] = defaultdict(list)
    for sample in samples:
        if sample.content_sha256:
            groups[sample.content_sha256].append(sample)
    return {key: value for key, value in groups.items() if len(value) > 1}


def approximate_duplicate_pairs(samples: List[CandidateSample]) -> List[Tuple[CandidateSample, CandidateSample, int]]:
    pairs: List[Tuple[CandidateSample, CandidateSample, int]] = []
    comparable = [sample for sample in samples if sample.perceptual_hash is not None]
    for index, left in enumerate(comparable):
        for right in comparable[index + 1 :]:
            if left.content_sha256 and left.content_sha256 == right.content_sha256:
                continue
            distance = hamming_distance(left.perceptual_hash or 0, right.perceptual_hash or 0)
            if distance <= APPROXIMATE_HASH_DISTANCE:
                pairs.append((left, right, distance))
    return pairs


def cross_split_issues(samples: Iterable[CandidateSample]) -> List[str]:
    groups: Dict[str, Set[str]] = defaultdict(set)
    members: Dict[str, List[str]] = defaultdict(list)
    for sample in samples:
        if sample.content_sha256:
            groups[sample.content_sha256].add(sample.split)
            members[sample.content_sha256].append(sample.sample_key)
    return [
        f"{digest[:16]} splits={sorted(groups[digest])} samples={members[digest]}"
        for digest in groups
        if len(groups[digest]) > 1
    ]


def conflicting_label_issues(samples: Iterable[CandidateSample]) -> List[str]:
    labels: Dict[str, Set[int]] = defaultdict(set)
    members: Dict[str, List[str]] = defaultdict(list)
    for sample in samples:
        if sample.content_sha256:
            labels[sample.content_sha256].add(sample.label)
            members[sample.content_sha256].append(sample.sample_key)
    return [
        f"{digest[:16]} labels={sorted(labels[digest])} samples={members[digest]}"
        for digest in labels
        if len(labels[digest]) > 1
    ]


def family_cross_split_issues(samples: Iterable[CandidateSample]) -> List[str]:
    groups: Dict[str, List[CandidateSample]] = defaultdict(list)
    for sample in samples:
        groups[sample.group_key].append(sample)
    return [
        f"{group} splits={sorted({sample.split for sample in members})} samples={[sample.sample_key for sample in members]}"
        for group, members in groups.items()
        if len({sample.split for sample in members}) > 1
    ]


def validate_candidate_metadata(samples: Iterable[CandidateSample]) -> Dict[str, List[str]]:
    issues: Dict[str, List[str]] = defaultdict(list)
    for sample in samples:
        if sample.source_license_state != "APPROVED":
            issues["source_license"].append(sample.sample_key)
        if sample.review_state != "CLOSED":
            issues["review_not_closed"].append(sample.sample_key)
        if sample.quality_state != "APPROVED":
            issues["quality_not_approved"].append(sample.sample_key)
        if sample.difficulty not in {"NORMAL", "HARD"}:
            issues["difficulty_missing_or_invalid"].append(sample.sample_key)
        if not sample.capture_id:
            issues["capture_id_missing"].append(sample.sample_key)
        if not sample.source_review_id:
            issues["source_review_id_missing"].append(sample.sample_key)
        if not sample.source:
            issues["source_missing"].append(sample.sample_key)
        if sample.errors:
            issues["sample_integrity"].append(f"{sample.sample_key}:{','.join(sample.errors)}")
    return dict(issues)


def deduplicate_samples(samples: List[CandidateSample]) -> Tuple[List[CandidateSample], List[str], List[str]]:
    """返回保留样本、精确去重项和近似去重项。冲突由上层审计阻断。"""

    kept: List[CandidateSample] = []
    exact_removed: List[str] = []
    approximate_removed: List[str] = []
    seen_hashes: Set[str] = set()
    for sample in sorted(samples, key=lambda item: item.sample_key):
        if sample.content_sha256 and sample.content_sha256 in seen_hashes:
            exact_removed.append(sample.sample_key)
            continue
        near_match = False
        if sample.perceptual_hash is not None:
            for previous in kept:
                if previous.perceptual_hash is None:
                    continue
                if hamming_distance(sample.perceptual_hash, previous.perceptual_hash) <= APPROXIMATE_HASH_DISTANCE:
                    near_match = True
                    break
        if near_match:
            approximate_removed.append(sample.sample_key)
            continue
        kept.append(sample)
        if sample.content_sha256:
            seen_hashes.add(sample.content_sha256)
    return kept, exact_removed, approximate_removed


def version_diff(current: Iterable[CandidateSample], parent_manifest: Path) -> Dict[str, Any]:
    parent_keys: Set[str] = set()
    if parent_manifest.is_file():
        with parent_manifest.open(newline="", encoding="utf-8-sig") as stream:
            parent_keys = {
                _required_value(row, ("sample_key", "sample_id"))
                for row in csv.DictReader(stream)
            }
            parent_keys.discard("")
    current_keys = {sample.sample_key for sample in current}
    return {
        "parent_manifest": str(parent_manifest.relative_to(REPO_ROOT)) if parent_manifest.is_relative_to(REPO_ROOT) else str(parent_manifest),
        "added_sample_keys": sorted(current_keys - parent_keys),
        "removed_sample_keys": sorted(parent_keys - current_keys),
        "unchanged_sample_count": len(current_keys & parent_keys),
        "current_sample_count": len(current_keys),
        "parent_sample_count": len(parent_keys),
    }


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_dataset(
    samples: List[CandidateSample],
    manifest_path: Path,
    parent_manifest: Path,
    version_name: str,
    description: str,
    package_dir: Path,
) -> Dict[str, Any]:
    if package_dir.exists() and any(package_dir.iterdir()):
        raise FileExistsError(f"不可变数据集版本已存在，拒绝覆盖：{package_dir}")
    package_dir.mkdir(parents=True, exist_ok=True)

    metadata_issues = validate_candidate_metadata(samples)
    exact_groups = exact_duplicate_groups(samples)
    cross_split = cross_split_issues(samples)
    conflicts = conflicting_label_issues(samples)
    family_leak = family_cross_split_issues(samples)
    approximate_pairs = approximate_duplicate_pairs(samples)
    kept, exact_removed, approximate_removed = deduplicate_samples(samples)
    approximate_conflicts = [
        f"{left.sample_key}:{right.sample_key}:distance={distance}"
        for left, right, distance in approximate_pairs
        if left.split != right.split or left.label != right.label
    ]
    difficulty_counts: Dict[str, int] = defaultdict(int)
    for sample in kept:
        difficulty_counts[sample.difficulty] += 1
    blockers: Dict[str, Any] = {
        "metadata": metadata_issues,
        "cross_split_hash": cross_split,
        "conflicting_labels": conflicts,
        "family_cross_split": family_leak,
        "approximate_duplicate_conflicts": approximate_conflicts,
        "image_decoder": ["Pillow unavailable"] if Image is None else [],
    }
    has_blockers = bool(
        any(metadata_issues.values())
        or cross_split
        or conflicts
        or family_leak
        or approximate_conflicts
        or Image is None
        or not {"NORMAL", "HARD"}.issubset(difficulty_counts)
    )
    accepted = [] if has_blockers else kept

    split_counts: Dict[str, int] = defaultdict(int)
    label_counts: Dict[str, int] = defaultdict(int)
    for sample in accepted:
        split_counts[sample.split] += 1
        label_counts[sample.label_name] += 1
    manifest_rows = [
        {
            "sample_key": sample.sample_key,
            "image_path": sample.image_path,
            "mask_path": sample.mask_path,
            "label": sample.label,
            "label_name": sample.label_name,
            "split": sample.split,
            "group_key": sample.group_key,
            "content_sha256": sample.content_sha256,
            "mask_sha256": sample.mask_sha256,
            "image_size_bytes": sample.image_size_bytes,
            "mask_size_bytes": sample.mask_size_bytes,
            "image_width": sample.image_width,
            "image_height": sample.image_height,
            "mask_width": sample.mask_width,
            "mask_height": sample.mask_height,
            "mask_has_content": sample.mask_has_content,
            "source": sample.source,
            "source_license_state": sample.source_license_state,
            "review_state": sample.review_state,
            "quality_state": sample.quality_state,
            "difficulty": sample.difficulty,
            "capture_id": sample.capture_id,
            "source_review_id": sample.source_review_id,
        }
        for sample in accepted
    ]
    columns = list(manifest_rows[0].keys()) if manifest_rows else [
        "sample_key", "image_path", "mask_path", "label", "label_name", "split", "group_key",
        "content_sha256", "mask_sha256", "image_size_bytes", "mask_size_bytes", "image_width", "image_height",
        "mask_width", "mask_height", "mask_has_content", "source", "source_license_state",
        "review_state", "quality_state", "difficulty", "capture_id", "source_review_id",
    ]
    with (package_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(manifest_rows)

    statistics = {
        "input_samples": len(samples),
        "accepted_samples": len(accepted),
        "quarantined_samples": len(samples) - len(accepted),
        "split_counts": dict(split_counts),
        "label_counts": dict(label_counts),
        "difficulty_counts": dict(difficulty_counts),
        "unique_hashes": len({sample.content_sha256 for sample in accepted if sample.content_sha256}),
        "total_images_bytes": sum(sample.image_size_bytes for sample in accepted),
        "total_masks_bytes": sum(sample.mask_size_bytes for sample in accepted),
    }
    statistics["total_bytes"] = statistics["total_images_bytes"] + statistics["total_masks_bytes"]
    _json_write(package_dir / "statistics.json", statistics)

    checksum_lines = []
    for sample in sorted(accepted, key=lambda item: item.sample_key):
        checksum_lines.append(f"{sample.content_sha256}  {sample.image_path}")
        checksum_lines.append(f"{sample.mask_sha256}  {sample.mask_path}")
    (package_dir / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    audit = {
        "schema_version": "p6-02-audit.v1",
        "exact_duplicate_group_count": len(exact_groups),
        "exact_duplicate_removed": exact_removed,
        "approximate_duplicate_pair_count": len(approximate_pairs),
        "approximate_duplicate_removed": approximate_removed,
        "approximate_duplicate_conflicts": approximate_conflicts,
        "cross_split_hash_issues": cross_split,
        "conflicting_label_issues": conflicts,
        "family_cross_split_issues": family_leak,
        "metadata_issues": metadata_issues,
        "difficulty_counts": dict(difficulty_counts),
        "quarantined_sample_keys": sorted({sample.sample_key for sample in samples} - {sample.sample_key for sample in accepted}),
    }
    _json_write(package_dir / "split-audit.json", audit)
    quarantine_status = "BLOCKED" if has_blockers else ("QUARANTINED" if exact_removed or approximate_removed else "EMPTY")
    _json_write(package_dir / "quarantine.json", {
        "status": quarantine_status,
        "blockers": blockers,
        "exact_duplicate_removed": exact_removed,
        "approximate_duplicate_removed": approximate_removed,
    })
    _json_write(package_dir / "diff-report.json", version_diff(accepted, parent_manifest))

    provenance = {
        "schema_version": "p6-02-provenance.v1",
        "version_name": version_name,
        "description": description,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "candidate_manifest": str(manifest_path.relative_to(REPO_ROOT)) if manifest_path.is_relative_to(REPO_ROOT) else str(manifest_path),
        "candidate_manifest_sha256": sha256_file(manifest_path),
        "parent_manifest": str(parent_manifest.relative_to(REPO_ROOT)) if parent_manifest.is_relative_to(REPO_ROOT) else str(parent_manifest),
        "input_samples": len(samples),
        "accepted_samples": len(accepted),
        "ordinary_and_hard_required": True,
        "immutable": True,
        "manifest_sha256": "",
        "production_claim_allowed": False,
    }
    provenance["manifest_sha256"] = sha256_file(package_dir / "manifest.csv")
    _json_write(package_dir / "provenance.json", provenance)
    _json_write(package_dir / "approval.json", {
        "schema_version": "p6-02-approval.v1",
        "version_name": version_name,
        "state": "DRAFT",
        "note": "候选数据集自动构建，待独立质量负责人审批",
        "generated_by": "dataset-builder",
        "independent_approval_required": True,
        "production_claim_allowed": False,
        "immutable": True,
    })

    report = {
        "schema_version": "p6-02-report.v1",
        "version_name": version_name,
        "status": "COMPLETE" if not has_blockers and accepted else "BLOCKED",
        "input_samples": len(samples),
        "accepted_samples": len(accepted),
        "quarantined_samples": len(samples) - len(accepted),
        "blocker_count": sum(len(value) if isinstance(value, list) else sum(len(items) for items in value.values()) for value in blockers.values()),
        "statistics": statistics,
        "production_claim_allowed": False,
    }
    _json_write(package_dir / "report.json", report)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="构建 P6-02 生产候选数据集版本")
    parser.add_argument("--candidate-manifest", type=Path, default=DEFAULT_CANDIDATE_MANIFEST)
    parser.add_argument("--parent-manifest", type=Path, default=DEFAULT_PARENT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--version", default="production-candidate-v1")
    args = parser.parse_args(argv)
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        print(f"构建失败：拒绝覆盖已有不可变受控输出目录：{output_dir}", file=sys.stderr)
        return 2
    try:
        samples, load_errors = load_candidate_manifest(args.candidate_manifest.resolve())
        if load_errors:
            print(json.dumps({"status": "BLOCKED", "errors": load_errors}, ensure_ascii=False, indent=2))
            return 2
        report = build_dataset(
            samples,
            args.candidate_manifest.resolve(),
            args.parent_manifest.resolve(),
            args.version,
            "带准入证据、去重、组级划分和版本差异的生产候选数据集",
            output_dir / args.version,
        )
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"status": report["status"], "version": args.version, "input_samples": report["input_samples"], "accepted_samples": report["accepted_samples"], "blocker_count": report["blocker_count"], "output": str(output_dir)}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
