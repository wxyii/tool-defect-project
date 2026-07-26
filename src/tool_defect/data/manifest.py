"""Build a deterministic image/mask/annotation manifest."""

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
import random
from typing import Iterable, List


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class ManifestRow:
    sample_id: str
    image_path: str
    mask_path: str
    annotation_path: str
    label: int
    label_name: str
    split: str


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _find_mask(image: Path, mask_dir: Path) -> Path:
    candidates = (
        mask_dir / image.name,
        mask_dir / f"{image.name}.png",
        mask_dir / f"{image.stem}.png",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ValueError(f"missing mask for image: {image}")


def _split_count(sample_count: int, fraction: float, split_name: str) -> int:
    if not 0 <= fraction < 1:
        raise ValueError(f"{split_name}_fraction must be in the range [0, 1)")
    if fraction == 0 or sample_count < 2:
        return 0
    return min(sample_count - 1, max(1, round(sample_count * fraction)))


def build_manifest(
    data_root,
    validation_fraction=0.2,
    test_fraction=0.2,
    seed=1,
):
    data_root = Path(data_root).resolve()
    class_specs = (("qualified", 0), ("unqualified", 1))
    all_rows: List[ManifestRow] = []
    randomizer = random.Random(seed)

    for label_name, label in class_specs:
        image_dir = data_root / "images" / label_name
        mask_dir = data_root / "masks" / label_name
        annotation_dir = data_root / "annotations" / "labelme_json"
        images = sorted(
            (
                path
                for path in image_dir.iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            ),
            key=lambda path: path.name.lower(),
        )
        if not images:
            raise ValueError(f"no images found in {image_dir}")

        shuffled_names = [image.name for image in images]
        randomizer.shuffle(shuffled_names)
        test_count = _split_count(len(images), test_fraction, "test")
        test_names = set(shuffled_names[:test_count])
        remaining_names = shuffled_names[test_count:]
        validation_count = _split_count(
            len(remaining_names),
            validation_fraction,
            "validation",
        )
        validation_names = set(remaining_names[:validation_count])

        for image in images:
            mask = _find_mask(image, mask_dir)
            annotation = annotation_dir / f"{image.stem}.json"
            if label_name == "unqualified" and not annotation.is_file():
                raise ValueError(f"missing annotation for image: {image}")
            all_rows.append(
                ManifestRow(
                    sample_id=f"{label_name}/{image.name}",
                    image_path=_relative(image, data_root),
                    mask_path=_relative(mask, data_root),
                    annotation_path=(
                        _relative(annotation, data_root)
                        if label_name == "unqualified"
                        else ""
                    ),
                    label=label,
                    label_name=label_name,
                    split=(
                        "test"
                        if image.name in test_names
                        else (
                            "validation"
                            if image.name in validation_names
                            else "train"
                        )
                    ),
                )
            )

    return all_rows


def write_manifest(rows: Iterable[ManifestRow], destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sample_id",
        "image_path",
        "mask_path",
        "annotation_path",
        "label",
        "label_name",
        "split",
    ]
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
