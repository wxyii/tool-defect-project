"""Create an auditable, leakage-aware manifest for multitask retraining."""

import csv
import hashlib
import random
import re
from pathlib import Path


FIELDNAMES = [
    "sample_id",
    "image_path",
    "mask_path",
    "annotation_path",
    "label",
    "label_name",
    "split",
]
CONFLICTING_SAMPLE_IDS = {
    "unqualified/2.png",
    "unqualified/16.png",
}


def _read_manifest(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _family_key(row):
    stem = Path(row["image_path"]).stem.lower().replace(" ", "")
    match = re.fullmatch(r"(\d+)(?:-+\d+)?", stem)
    family = match.group(1) if match else stem
    return f"{row['label_name']}:{family}"


def _deduplicate(rows, data_root):
    retained = []
    seen = set()
    removed = 0
    for row in sorted(rows, key=lambda item: item["sample_id"].lower()):
        digest = _sha256(data_root / row["image_path"])
        key = (row["label_name"], digest)
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        copied = dict(row)
        copied["_image_sha256"] = digest
        retained.append(copied)
    return retained, removed


def _allocate_class(rows, seed, validation_fraction, test_fraction):
    grouped = {}
    for row in rows:
        grouped.setdefault(_family_key(row), []).append(row)
    groups = [
        sorted(group, key=lambda row: row["sample_id"].lower())
        for _, group in sorted(grouped.items())
    ]
    random.Random(seed).shuffle(groups)
    if len(groups) < 3:
        raise ValueError(
            f"at least three independent groups are required for {rows[0]['label_name']}"
        )

    sample_count = len(rows)
    targets = {
        "test": max(1, round(sample_count * test_fraction)),
        "validation": max(1, round(sample_count * validation_fraction)),
    }
    assigned = {"test": [], "validation": [], "train": []}
    remaining = list(groups)
    for split in ("test", "validation"):
        while len(remaining) > 1 and sum(len(group) for group in assigned[split]) < targets[split]:
            assigned[split].append(remaining.pop(0))
    assigned["train"] = remaining

    output = []
    for split in ("train", "validation", "test"):
        for group in assigned[split]:
            for row in group:
                copied = {name: row.get(name, "") for name in FIELDNAMES}
                copied["label"] = int(copied["label"])
                copied["split"] = split
                copied["_image_sha256"] = row["_image_sha256"]
                output.append(copied)
    return output


def build_retrain_manifest(
    source_manifest,
    data_root,
    seed=1,
    validation_fraction=0.16,
    test_fraction=0.20,
):
    """Return leakage-aware rows and a JSON-serializable audit dictionary."""
    if validation_fraction <= 0 or test_fraction <= 0:
        raise ValueError("validation_fraction and test_fraction must be positive")
    if validation_fraction + test_fraction >= 1:
        raise ValueError("validation_fraction + test_fraction must be below 1")

    data_root = Path(data_root)
    source_rows = _read_manifest(source_manifest)
    filtered = [
        row
        for row in source_rows
        if row["sample_id"] not in CONFLICTING_SAMPLE_IDS
    ]
    excluded = len(source_rows) - len(filtered)
    deduplicated, duplicate_count = _deduplicate(filtered, data_root)

    output = []
    for class_offset, label_name in enumerate(("qualified", "unqualified")):
        class_rows = [
            row for row in deduplicated if row["label_name"] == label_name
        ]
        if not class_rows:
            raise ValueError(f"manifest contains no {label_name} samples")
        output.extend(
            _allocate_class(
                class_rows,
                seed=int(seed) + class_offset * 1009,
                validation_fraction=validation_fraction,
                test_fraction=test_fraction,
            )
        )

    digest_splits = {}
    for row in output:
        digest_splits.setdefault(row["_image_sha256"], set()).add(row["split"])
    cross_split = sum(len(splits) > 1 for splits in digest_splits.values())

    clean_rows = []
    for row in sorted(
        output,
        key=lambda item: (
            ("train", "validation", "test").index(item["split"]),
            int(item["label"]),
            item["sample_id"].lower(),
        ),
    ):
        clean_rows.append({name: row.get(name, "") for name in FIELDNAMES})

    audit = {
        "seed": int(seed),
        "validation_fraction": float(validation_fraction),
        "test_fraction": float(test_fraction),
        "source_samples": len(source_rows),
        "excluded_conflicting": excluded,
        "conflicting_sample_ids": sorted(
            row["sample_id"]
            for row in source_rows
            if row["sample_id"] in CONFLICTING_SAMPLE_IDS
        ),
        "deduplicated_exact": duplicate_count,
        "final_samples": len(clean_rows),
        "cross_split_duplicate_hashes": cross_split,
        "split_counts": {
            split: sum(row["split"] == split for row in clean_rows)
            for split in ("train", "validation", "test")
        },
        "class_split_counts": {
            label_name: {
                split: sum(
                    row["label_name"] == label_name and row["split"] == split
                    for row in clean_rows
                )
                for split in ("train", "validation", "test")
            }
            for label_name in ("qualified", "unqualified")
        },
    }
    return clean_rows, audit


def write_retrain_manifest(rows, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(
            {name: row.get(name, "") for name in FIELDNAMES} for row in rows
        )
