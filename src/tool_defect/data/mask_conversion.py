"""Convert supplied Labelme polygon JSON files to binary PNG masks."""

import json
from pathlib import Path

import cv2
import numpy as np


def _write_png(path, image):
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise OSError(f"unable to encode mask: {path}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(path)


def convert_annotation(annotation_path, destination):
    annotation_path = Path(annotation_path)
    with annotation_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    mask = np.zeros(
        (int(data["imageHeight"]), int(data["imageWidth"])),
        dtype=np.uint8,
    )
    polygons = []
    for shape in data.get("shapes", []):
        points = shape.get("points") or shape.get("control_points")
        if not points:
            continue
        polygon = np.asarray(points, dtype=np.float32)
        if polygon.ndim > 2:
            polygon = polygon[:, 0, :]
        polygons.append(np.rint(polygon).astype(np.int32))
    if polygons:
        cv2.fillPoly(mask, polygons, 255)
    _write_png(destination, mask)
    return Path(destination)


def convert_directory(annotation_dir, output_dir):
    annotation_dir = Path(annotation_dir)
    output_dir = Path(output_dir)
    converted = []
    for annotation_path in sorted(annotation_dir.glob("*.json")):
        converted.append(
            convert_annotation(
                annotation_path,
                output_dir / f"{annotation_path.stem}.png",
            )
        )
    return converted
