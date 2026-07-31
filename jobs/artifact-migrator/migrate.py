#!/usr/bin/env python3
"""P6-01 历史数据导入与不可变基线

读取 data/manifests/ 中的历史清单 CSV，生成不可变数据集版本包。
两套版本分开保存，历史标签不形成生产放行记录。
"""

from __future__ import annotations

import csv
import argparse
import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from PIL import Image
except ImportError:
    Image = None


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
IMAGES_DIR = DATA_DIR / "images"
MASKS_DIR = DATA_DIR / "masks"
MANIFESTS_DIR = DATA_DIR / "manifests"
OUTPUT_DIR = REPO_ROOT / "jobs" / "artifact-migrator" / "controlled-output"

HASH_CHUNK = 65536


@dataclass
class SampleRecord:
    sample_id: str
    image_path: str
    mask_path: str
    annotation_path: str
    label: int
    label_name: str
    split: str
    image_sha256: Optional[str] = None
    image_size_bytes: int = 0
    image_width: int = 0
    image_height: int = 0
    image_channels: int = 0
    mask_sha256: Optional[str] = None
    mask_size_bytes: int = 0
    mask_has_content: Optional[bool] = None
    family_key: str = ""
    errors: List[str] = field(default_factory=list)


@dataclass
class ManifestSpec:
    name: str
    description: str
    source_csv: Path
    expected_samples: int


MANIFESTS: List[ManifestSpec] = [
    ManifestSpec(
        name="baseline-180",
        description="历史 180 样本原始确定性清单",
        source_csv=MANIFESTS_DIR / "dataset.csv",
        expected_samples=180,
    ),
    ManifestSpec(
        name="retrain-172",
        description="历史 172 样本审计重训练清单，已排除冲突与精确重复",
        source_csv=MANIFESTS_DIR / "retrain.csv",
        expected_samples=172,
    ),
]


def sha256_hex(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def check_image(file_path: Path) -> Tuple[str, int, int, int, int]:
    size = file_path.stat().st_size
    sha = sha256_hex(file_path)
    if Image is not None:
        with Image.open(file_path) as img:
            w, h_size = img.size
            channels = len(img.getbands())
    else:
        w, h_size, channels = 0, 0, 0
    return sha, size, w, h_size, channels


def check_mask_content(file_path: Path) -> bool:
    if Image is not None:
        with Image.open(file_path) as img:
            arr = np.array(img)
            return bool(np.count_nonzero(arr) > 0)
    return file_path.stat().st_size > 200


def filename_family(sample_id: str) -> str:
    parts = sample_id.split("/")
    if len(parts) == 2:
        name_part = parts[1]
        no_ext = name_part.rsplit(".", 1)[0]
        return f"{parts[0]}/{no_ext}"
    return sample_id.rsplit(".", 1)[0]


def load_manifest(manifest: ManifestSpec) -> Tuple[List[SampleRecord], Dict[str, List[str]]]:
    records: List[SampleRecord] = []
    errors: Dict[str, List[str]] = {}

    with open(manifest.source_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rec = SampleRecord(
                sample_id=row["sample_id"],
                image_path=row["image_path"],
                mask_path=row["mask_path"],
                annotation_path=row.get("annotation_path", ""),
                label=int(row["label"]),
                label_name=row["label_name"],
                split=row["split"],
                family_key=filename_family(row["sample_id"]),
            )

            img_path = DATA_DIR / rec.image_path
            if not img_path.exists():
                rec.errors.append(f"image_missing: {rec.image_path}")

            mask_path = DATA_DIR / rec.mask_path
            if not mask_path.exists():
                rec.errors.append(f"mask_missing: {rec.mask_path}")

            if img_path.exists():
                try:
                    sha, sz, w, h, ch = check_image(img_path)
                    rec.image_sha256 = sha
                    rec.image_size_bytes = sz
                    rec.image_width = w
                    rec.image_height = h
                    rec.image_channels = ch
                except Exception as exc:
                    rec.errors.append(f"image_decode: {rec.image_path} {exc}")

            if mask_path.exists():
                try:
                    rec.mask_sha256 = sha256_hex(mask_path)
                    rec.mask_size_bytes = mask_path.stat().st_size
                    rec.mask_has_content = check_mask_content(mask_path)
                except Exception as exc:
                    rec.errors.append(f"mask_decode: {rec.mask_path} {exc}")

            if rec.errors:
                errors[rec.sample_id] = rec.errors
            records.append(rec)

    return records, errors


def check_cross_split_leakage(records: List[SampleRecord]) -> List[str]:
    issues: List[str] = []
    by_hash: Dict[str, List[SampleRecord]] = defaultdict(list)

    for r in records:
        if r.image_sha256:
            by_hash[r.image_sha256].append(r)

    for sha, group in by_hash.items():
        splits = {r.split for r in group}
        if len(splits) > 1:
            ids = [r.sample_id for r in group]
            issues.append(f"cross_split_hash: {sha[:16]}... splits={splits} samples={ids}")

    return issues


def check_label_mask_consistency(records: List[SampleRecord]) -> List[str]:
    issues: List[str] = []
    for r in records:
        if r.label == 0 and r.mask_has_content:
            issues.append(f"qualified_nonempty_mask: {r.sample_id}")
        if r.label == 1 and r.mask_has_content is False:
            issues.append(f"unqualified_empty_mask: {r.sample_id}")
    return issues


def check_filename_family_leakage(records: List[SampleRecord]) -> List[str]:
    issues: List[str] = []
    by_family: Dict[str, List[SampleRecord]] = defaultdict(list)

    for r in records:
        by_family[r.family_key].append(r)

    for fam, group in by_family.items():
        splits = {r.split for r in group}
        if len(splits) > 1:
            ids = [r.sample_id for r in group]
            issues.append(f"family_cross_split: {fam} splits={splits} samples={ids}")

    return issues


def build_dataset_package(
    manifest: ManifestSpec,
    records: List[SampleRecord],
    errors: Dict[str, List[str]],
    version: str,
    package_dir: Path,
) -> Dict[str, object]:
    if package_dir.exists() and any(package_dir.iterdir()):
        raise FileExistsError(
            f"不可变数据集版本已存在，拒绝覆盖：{package_dir}"
        )
    package_dir.mkdir(parents=True, exist_ok=True)

    hashes = set()
    for r in records:
        if r.image_sha256:
            hashes.add(r.image_sha256)
    unique_hashes = len(hashes)

    split_counts: Dict[str, int] = defaultdict(int)
    label_counts: Dict[str, int] = defaultdict(int)
    class_split_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    error_count = sum(1 for e in errors.values() if e)
    broken_count = sum(1 for r in records if r.errors)

    for r in records:
        split_counts[r.split] += 1
        label_counts[r.label_name] += 1
        class_split_counts[r.label_name][r.split] += 1

    total_images_bytes = sum(r.image_size_bytes for r in records)
    total_masks_bytes = sum(r.mask_size_bytes for r in records)

    manifest_rows = []
    for r in records:
        manifest_rows.append({
            "sample_id": r.sample_id,
            "image_path": r.image_path,
            "mask_path": r.mask_path,
            "label": r.label,
            "label_name": r.label_name,
            "split": r.split,
            "image_sha256": r.image_sha256 or "",
            "image_size_bytes": r.image_size_bytes,
            "image_width": r.image_width,
            "image_height": r.image_height,
            "image_channels": r.image_channels,
            "mask_sha256": r.mask_sha256 or "",
            "mask_size_bytes": r.mask_size_bytes,
            "mask_has_content": r.mask_has_content,
            "family_key": r.family_key,
            "errors": len(r.errors),
        })

    with open(package_dir / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=manifest_rows[0].keys())
        writer.writeheader()
        writer.writerows(manifest_rows)

    provenance: Dict[str, object] = {
        "schema_version": "p6-01-provenance.v1",
        "package_version": version,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_manifest": str(manifest.source_csv.relative_to(REPO_ROOT)),
        "source_manifest_sha256": sha256_hex(manifest.source_csv),
        "source_snapshot": "source-snapshot.json",
        "description": manifest.description,
        "total_samples": len(records),
        "expected_samples": manifest.expected_samples,
        "excluded_from_source": 0,
        "production_claim_allowed": False,
    }
    with open(package_dir / "provenance.json", "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2, ensure_ascii=False)

    snapshot_objects: Dict[str, Dict[str, object]] = {}
    for record in records:
        for relative_path, digest, size in (
            (record.image_path, record.image_sha256, record.image_size_bytes),
            (record.mask_path, record.mask_sha256, record.mask_size_bytes),
        ):
            if digest:
                snapshot_objects[relative_path] = {
                    "path": relative_path,
                    "sha256": digest,
                    "size_bytes": size,
                }
    source_snapshot = {
        "schema_version": "p6-01-source-snapshot.v1",
        "source_manifest": str(manifest.source_csv.relative_to(REPO_ROOT)),
        "source_manifest_sha256": sha256_hex(manifest.source_csv),
        "objects": [snapshot_objects[key] for key in sorted(snapshot_objects)],
        "source_roots": [
            str(IMAGES_DIR.relative_to(REPO_ROOT)),
            str(MASKS_DIR.relative_to(REPO_ROOT)),
            str(MANIFESTS_DIR.relative_to(REPO_ROOT)),
        ],
        "original_dirs_preserved": True,
        "migration_write_scope": "jobs/artifact-migrator/controlled-output",
    }
    with open(package_dir / "source-snapshot.json", "w", encoding="utf-8") as f:
        json.dump(source_snapshot, f, indent=2, ensure_ascii=False)

    leakage = check_cross_split_leakage(records)
    fam_leak = check_filename_family_leakage(records)

    split_audit: Dict[str, object] = {
        "split_counts": dict(split_counts),
        "class_split_counts": {k: dict(v) for k, v in class_split_counts.items()},
        "cross_split_image_hashes": len(leakage),
        "cross_split_family_groups": len(fam_leak),
    }
    with open(package_dir / "split-audit.json", "w", encoding="utf-8") as f:
        json.dump(split_audit, f, indent=2, ensure_ascii=False)

    stats: Dict[str, object] = {
        "total_samples": len(records),
        "unique_image_hashes": unique_hashes,
        "split_counts": dict(split_counts),
        "label_counts": dict(label_counts),
        "class_split_counts": {k: dict(v) for k, v in class_split_counts.items()},
        "samples_with_errors": broken_count,
        "unique_error_categories": error_count,
        "total_images_bytes": total_images_bytes,
        "total_masks_bytes": total_masks_bytes,
        "total_bytes": total_images_bytes + total_masks_bytes,
    }
    with open(package_dir / "statistics.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    checksum_lines = []
    for r in sorted(records, key=lambda x: x.sample_id):
        if r.image_sha256:
            checksum_lines.append(f"{r.image_sha256}  {r.image_path}")
        if r.mask_sha256:
            checksum_lines.append(f"{r.mask_sha256}  {r.mask_path}")
    with open(package_dir / "checksums.sha256", "w", encoding="utf-8") as f:
        f.write("\n".join(checksum_lines) + "\n")

    approval: Dict[str, object] = {
        "schema_version": "p6-01-approval.v1",
        "package_name": manifest.name,
        "package_version": version,
        "state": "DRAFT",
        "note": "P6-01 历史数据导入自动生成，待质量负责人审批",
        "generated_by": "artifact-migrator",
        "production_claim_allowed": False,
    }
    with open(package_dir / "approval.json", "w", encoding="utf-8") as f:
        json.dump(approval, f, indent=2, ensure_ascii=False)

    consistency = check_label_mask_consistency(records)

    failure_list = []
    if errors:
        failure_list.append({
            "category": "file_errors",
            "count": len(errors),
            "details": {k: v for k, v in list(errors.items())[:50]},
        })
    if leakage:
        failure_list.append({"category": "cross_split_leakage", "count": len(leakage), "details": leakage[:50]})
    if fam_leak:
        failure_list.append({"category": "filename_family_leakage", "count": len(fam_leak), "details": fam_leak[:50]})
    if consistency:
        failure_list.append({"category": "label_mask_consistency", "count": len(consistency), "details": consistency[:50]})

    with open(package_dir / "failure-list.json", "w", encoding="utf-8") as f:
        json.dump(failure_list, f, indent=2, ensure_ascii=False)

    report: Dict[str, object] = {
        "package_name": manifest.name,
        "package_version": version,
        "status": "BLOCKED" if (errors or leakage or fam_leak or consistency) else "COMPLETE",
        "total_samples": len(records),
        "expected_samples": manifest.expected_samples,
        "sample_count_match": len(records) == manifest.expected_samples,
        "unique_image_hashes": unique_hashes,
        "file_errors": len(errors),
        "cross_split_issues": len(leakage),
        "family_leak_issues": len(fam_leak),
        "label_consistency_issues": len(consistency),
        "statistics": stats,
    }

    with open(package_dir / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


def check_directory_readonly(manifest: ManifestSpec) -> Dict[str, object]:
    """只记录迁移写入边界；不以目录存在冒充已完成只读验证。"""

    source_dirs = []
    for dir_label, path in [("images", IMAGES_DIR), ("masks", MASKS_DIR)]:
        if path.exists():
            source_dirs.append({"name": dir_label, "path": str(path.relative_to(REPO_ROOT))})
    if MANIFESTS_DIR.exists():
        source_dirs.append({"name": "manifests", "path": str(MANIFESTS_DIR.relative_to(REPO_ROOT))})
    return {
        "source_dirs": source_dirs,
        "original_dirs_preserved": True,
        "migration_write_scope": "jobs/artifact-migrator/controlled-output",
        "note": "目录存在不等于只读验证；须由 source-snapshot 与严格验证器重算确认",
        "manifest": str(manifest.source_csv.relative_to(REPO_ROOT)),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成 P6-01 历史数据不可变清单")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="新的受控输出目录；已有非空目录会被拒绝覆盖",
    )
    args = parser.parse_args(argv)
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        print(
            f"迁移失败：拒绝覆盖已有不可变受控输出目录：{output_dir}",
            file=sys.stderr,
        )
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)

    all_reports: Dict[str, object] = {}
    overall_status = "COMPLETE"
    overall_errors: List[Dict[str, object]] = []

    for i, manifest in enumerate(MANIFESTS):
        version = f"1.0.{i}"
        print(f"\n=== {manifest.name} (v{version}) ===")
        print(f"  Source: {manifest.source_csv}")

        records, errors = load_manifest(manifest)

        print(f"  Samples loaded: {len(records)} (expected {manifest.expected_samples})")
        if len(records) != manifest.expected_samples:
            print(f"  WARNING: sample count mismatch!")
            overall_errors.append({
                "manifest": manifest.name,
                "issue": f"count_mismatch: {len(records)} != {manifest.expected_samples}",
            })

        report = build_dataset_package(manifest, records, errors, version, output_dir / manifest.name)

        print(f"  Status: {report['status']}")
        print(f"  File errors: {report['file_errors']}")
        print(f"  Cross-split issues: {report['cross_split_issues']}")
        print(f"  Family leak issues: {report['family_leak_issues']}")
        print(f"  Label consistency issues: {report['label_consistency_issues']}")
        print(f"  Unique image hashes: {report['unique_image_hashes']}")

        if report["file_errors"] > 0:
            print(f"  Sample file error details:")
            for sid, errs in list(errors.items())[:20]:
                print(f"    {sid}: {errs}")

        all_reports[manifest.name] = report
        if report["status"] == "BLOCKED":
            overall_status = "BLOCKED"

    read_only_notes = check_directory_readonly(MANIFESTS[0])

    summary: Dict[str, object] = {
        "migrator_version": "1.0.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "overall_status": overall_status,
        "manifests": all_reports,
        "overall_errors": overall_errors,
        "read_only_notes": read_only_notes,
        "object_registration": {
            "status": "NOT_RUN",
            "production_claim_allowed": False,
            "note": "需在独立对象存储根目录上运行 register_objects.py",
        },
        "backup_and_rollback": {
            "status": "NOT_RUN",
            "production_claim_allowed": False,
            "note": "需在独立备份和恢复根目录上执行验证",
        },
        "production_claim_allowed": False,
    }

    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    sha = sha256_hex(output_dir / "summary.json")
    print(f"\n=== Summary ===")
    print(f"  Overall status: {overall_status}")
    print(f"  Summary SHA-256: {sha}")
    print(f"  Output: {output_dir}")

    return 0 if overall_status == "COMPLETE" else 1


if __name__ == "__main__":
    sys.exit(main())
