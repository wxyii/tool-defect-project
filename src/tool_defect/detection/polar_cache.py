"""可校验、可重建的极坐标预处理缓存。"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from tool_defect.data.ring_geometry import (
    Circle,
    process_ring_image,
    read_color_image,
)


CACHE_VERSION = 1


@dataclass
class CachedRingResult:
    """检测阶段实际需要的环形几何结果。"""

    source: np.ndarray
    corrected: np.ndarray
    rectification_matrix: np.ndarray
    corrected_outer_circle: Circle
    polar_image: np.ndarray
    raw_inner_boundary: np.ndarray
    raw_outer_boundary: np.ndarray
    inner_boundary: np.ndarray
    outer_boundary: np.ndarray


def _pipeline_signature():
    geometry_path = Path(__file__).parents[1] / "data" / "ring_geometry.py"
    digest = hashlib.sha256()
    digest.update(f"polar-cache-{CACHE_VERSION}".encode("ascii"))
    digest.update(geometry_path.read_bytes())
    return digest.hexdigest()


def source_root_for(input_path):
    input_path = Path(input_path)
    return input_path if input_path.is_dir() else input_path.parent


def _relative_source(image_path, source_root):
    image_path = Path(image_path)
    source_root = Path(source_root)
    try:
        return image_path.resolve().relative_to(source_root.resolve()).as_posix()
    except ValueError:
        return image_path.name


def _entry_directory(image_path, source_root, cache_dir):
    relative = _relative_source(image_path, source_root)
    digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
    safe_stem = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in Path(image_path).stem
    )[:48]
    return Path(cache_dir) / f"{digest}_{safe_stem}"


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _write_png(path, image):
    success, encoded = cv2.imencode(
        ".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 6]
    )
    if not success:
        raise OSError(f"无法编码缓存图像：{path}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(str(path))


def _read_png(path):
    encoded = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取缓存图像：{path}")
    return image


def _metadata_for(
    image_path,
    source_root,
    ring_result,
    output_size,
    angle_samples,
):
    stat = Path(image_path).stat()
    return {
        "cache_version": CACHE_VERSION,
        "pipeline_signature": _pipeline_signature(),
        "source_relative_path": _relative_source(image_path, source_root),
        "source_absolute_path": str(Path(image_path).resolve()),
        "source_sha256": _file_sha256(image_path),
        "source_size": stat.st_size,
        "source_mtime_ns": stat.st_mtime_ns,
        "original_shape": list(ring_result.source.shape),
        "corrected_shape": list(ring_result.corrected.shape),
        "polar_shape": list(ring_result.polar_image.shape),
        "output_size": int(output_size),
        "angle_samples": int(angle_samples),
    }


def save_cache_entry(
    image_path,
    source_root,
    cache_dir,
    ring_result,
    *,
    output_size,
    angle_samples,
):
    entry_dir = _entry_directory(image_path, source_root, cache_dir)
    entry_dir.mkdir(parents=True, exist_ok=True)
    _write_png(entry_dir / "polar.png", ring_result.polar_image)
    outer = ring_result.corrected_outer_circle
    np.savez_compressed(
        entry_dir / "geometry.npz",
        raw_inner_boundary=ring_result.raw_inner_boundary.astype(np.float32),
        raw_outer_boundary=ring_result.raw_outer_boundary.astype(np.float32),
        inner_boundary=ring_result.inner_boundary.astype(np.float32),
        outer_boundary=ring_result.outer_boundary.astype(np.float32),
        rectification_matrix=ring_result.rectification_matrix.astype(np.float32),
        corrected_outer_circle=np.asarray(
            [outer.x, outer.y, outer.radius], dtype=np.float32
        ),
        corrected_shape=np.asarray(ring_result.corrected.shape, dtype=np.int32),
        original_shape=np.asarray(ring_result.source.shape, dtype=np.int32),
    )
    metadata = _metadata_for(
        image_path,
        source_root,
        ring_result,
        output_size,
        angle_samples,
    )
    (entry_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return entry_dir


def _read_metadata(entry_dir):
    metadata_path = Path(entry_dir) / "metadata.json"
    if not metadata_path.is_file():
        return None
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def cache_entry_is_valid(
    image_path,
    source_root,
    entry_dir,
    *,
    output_size,
    angle_samples,
):
    entry_dir = Path(entry_dir)
    if not (entry_dir / "polar.png").is_file():
        return False
    if not (entry_dir / "geometry.npz").is_file():
        return False
    metadata = _read_metadata(entry_dir)
    if metadata is None:
        return False
    expected = {
        "cache_version": CACHE_VERSION,
        "pipeline_signature": _pipeline_signature(),
        "source_relative_path": _relative_source(image_path, source_root),
        "output_size": int(output_size),
        "angle_samples": int(angle_samples),
    }
    if any(metadata.get(key) != value for key, value in expected.items()):
        return False
    stat = Path(image_path).stat()
    if (
        metadata.get("source_size") == stat.st_size
        and metadata.get("source_mtime_ns") == stat.st_mtime_ns
    ):
        return True
    return metadata.get("source_sha256") == _file_sha256(image_path)


def load_cache_entry(
    image_path,
    source_root,
    cache_dir,
    *,
    load_source,
    entry_dir=None,
):
    if entry_dir is None:
        entry_dir = _entry_directory(image_path, source_root, cache_dir)
    entry_dir = Path(entry_dir)
    polar_image = _read_png(entry_dir / "polar.png")
    with np.load(entry_dir / "geometry.npz", allow_pickle=False) as geometry:
        corrected_shape = tuple(int(value) for value in geometry["corrected_shape"])
        original_shape = tuple(int(value) for value in geometry["original_shape"])
        outer_values = geometry["corrected_outer_circle"]
        result = CachedRingResult(
            source=(
                read_color_image(image_path)
                if load_source
                else np.empty((0, 0, 3), dtype=np.uint8)
            ),
            corrected=np.empty(corrected_shape, dtype=np.uint8),
            rectification_matrix=geometry["rectification_matrix"].astype(
                np.float32
            ),
            corrected_outer_circle=Circle(
                float(outer_values[0]),
                float(outer_values[1]),
                float(outer_values[2]),
            ),
            polar_image=polar_image,
            raw_inner_boundary=geometry["raw_inner_boundary"].astype(np.float32),
            raw_outer_boundary=geometry["raw_outer_boundary"].astype(np.float32),
            inner_boundary=geometry["inner_boundary"].astype(np.float32),
            outer_boundary=geometry["outer_boundary"].astype(np.float32),
        )
    if load_source and result.source.shape != original_shape:
        raise ValueError(f"原图尺寸与缓存不一致：{image_path}")
    return result


def _find_entry_by_absolute_source(
    image_path,
    cache_dir,
    *,
    output_size,
    angle_samples,
):
    absolute_source = str(Path(image_path).resolve())
    stat = Path(image_path).stat()
    for metadata_path in Path(cache_dir).glob("*/metadata.json"):
        metadata = _read_metadata(metadata_path.parent)
        if metadata is None:
            continue
        if metadata.get("source_absolute_path") != absolute_source:
            continue
        if metadata.get("cache_version") != CACHE_VERSION:
            continue
        if metadata.get("pipeline_signature") != _pipeline_signature():
            continue
        if metadata.get("output_size") != int(output_size):
            continue
        if metadata.get("angle_samples") != int(angle_samples):
            continue
        if not (metadata_path.parent / "polar.png").is_file():
            continue
        if not (metadata_path.parent / "geometry.npz").is_file():
            continue
        stat_matches = (
            metadata.get("source_size") == stat.st_size
            and metadata.get("source_mtime_ns") == stat.st_mtime_ns
        )
        if stat_matches or metadata.get("source_sha256") == _file_sha256(
            image_path
        ):
            return metadata_path.parent
    return None


def load_or_build_cache(
    image_path,
    source_root,
    cache_dir,
    *,
    output_size,
    angle_samples,
    load_source,
):
    entry_dir = _entry_directory(image_path, source_root, cache_dir)
    if cache_entry_is_valid(
        image_path,
        source_root,
        entry_dir,
        output_size=output_size,
        angle_samples=angle_samples,
    ):
        metadata = _read_metadata(entry_dir)
        absolute_source = str(Path(image_path).resolve())
        if metadata.get("source_absolute_path") != absolute_source:
            metadata["source_absolute_path"] = absolute_source
            (entry_dir / "metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return (
            load_cache_entry(
                image_path, source_root, cache_dir, load_source=load_source
            ),
            "hit",
        )
    existing_entry = _find_entry_by_absolute_source(
        image_path,
        cache_dir,
        output_size=output_size,
        angle_samples=angle_samples,
    )
    if existing_entry is not None:
        return (
            load_cache_entry(
                image_path,
                source_root,
                cache_dir,
                load_source=load_source,
                entry_dir=existing_entry,
            ),
            "hit",
        )
    image = read_color_image(image_path)
    ring_result = process_ring_image(
        image,
        output_size=output_size,
        angle_samples=angle_samples,
    )
    save_cache_entry(
        image_path,
        source_root,
        cache_dir,
        ring_result,
        output_size=output_size,
        angle_samples=angle_samples,
    )
    if load_source:
        return ring_result, "rebuilt"
    return (
        load_cache_entry(
            image_path, source_root, cache_dir, load_source=False
        ),
        "rebuilt",
    )


def build_polar_cache(
    input_path,
    cache_dir,
    image_paths,
    *,
    output_size=512,
    angle_samples=1440,
):
    source_root = source_root_for(input_path)
    hits = 0
    rebuilt = 0
    failures = []
    entries = []
    for image_path in image_paths:
        try:
            _, state = load_or_build_cache(
                image_path,
                source_root,
                cache_dir,
                output_size=output_size,
                angle_samples=angle_samples,
                load_source=False,
            )
            hits += int(state == "hit")
            rebuilt += int(state == "rebuilt")
            entries.append(
                {
                    "source": _relative_source(image_path, source_root),
                    "entry": _entry_directory(
                        image_path, source_root, cache_dir
                    ).name,
                    "state": state,
                }
            )
        except Exception as error:
            failures.append(
                {
                    "source": _relative_source(image_path, source_root),
                    "message": str(error),
                }
            )
    report = {
        "input_images": len(image_paths),
        "cache_hits": hits,
        "cache_rebuilt": rebuilt,
        "failed_images": len(failures),
        "cache_version": CACHE_VERSION,
        "pipeline_signature": _pipeline_signature(),
        "entries": entries,
        "failures": failures,
    }
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "cache_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report
