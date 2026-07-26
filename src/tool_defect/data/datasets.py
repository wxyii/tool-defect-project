"""Load manifest-bound arrays for classification and segmentation."""

import csv
from pathlib import Path

import numpy as np

from tool_defect.data.preprocess import load_image, load_mask


def _read_rows(manifest_path, split):
    with Path(manifest_path).open(newline="", encoding="utf-8-sig") as handle:
        return [row for row in csv.DictReader(handle) if row["split"] == split]


def _balanced_limit(rows, max_samples):
    if max_samples is None or len(rows) <= max_samples:
        return rows
    by_label = {}
    for row in rows:
        by_label.setdefault(row["label_name"], []).append(row)
    selected = []
    labels = sorted(by_label)
    while len(selected) < max_samples and any(by_label.values()):
        for label in labels:
            if by_label[label] and len(selected) < max_samples:
                selected.append(by_label[label].pop(0))
    return selected


def load_manifest_rows(manifest_path, split, max_samples=None):
    return _balanced_limit(_read_rows(manifest_path, split), max_samples)


def load_dataset(
    manifest_path,
    data_root,
    split,
    image_size=256,
    max_samples=None,
    include_masks=False,
    return_rows=False,
):
    data_root = Path(data_root)
    rows = load_manifest_rows(manifest_path, split, max_samples)
    if not rows:
        raise ValueError(f"manifest contains no rows for split '{split}'")

    images = np.stack(
        [load_image(data_root / row["image_path"], image_size) for row in rows]
    )
    label_ids = np.asarray([int(row["label"]) for row in rows], dtype=np.int32)
    labels = np.eye(2, dtype=np.float32)[label_ids]
    if not include_masks:
        return (images, labels, rows) if return_rows else (images, labels)
    masks = np.stack(
        [load_mask(data_root / row["mask_path"], image_size) for row in rows]
    )
    return (
        (images, labels, masks, rows)
        if return_rows
        else (images, labels, masks)
    )
