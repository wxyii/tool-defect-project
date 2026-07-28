"""从原始清单生成环形区域或边界归一化展开训练数据集。"""

from collections import Counter
import csv
import json
from pathlib import Path

import cv2
import numpy as np

from tool_defect.data.manifest import ManifestRow, write_manifest
from tool_defect.data.ring_geometry import (
    extract_adaptive_annular_roi,
    process_image_path,
)


GENERATOR_VERSION = 1
DATASET_MODES = ("adaptive-annular", "boundary-normalized")
_MANIFEST_FIELDS = {
    "sample_id",
    "image_path",
    "mask_path",
    "annotation_path",
    "label",
    "label_name",
    "split",
}
_PROVENANCE_FIELDS = [
    "sample_id",
    "source_image_path",
    "source_mask_path",
    "source_annotation_path",
    "output_image_path",
    "output_mask_path",
    "label",
    "label_name",
    "split",
    "source_height",
    "source_width",
    "output_height",
    "output_width",
    "source_foreground_pixels",
    "source_foreground_fraction",
    "output_foreground_pixels",
    "output_foreground_fraction",
    "cache_state",
]


def _read_manifest(manifest_path):
    manifest_path = Path(manifest_path)
    with manifest_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = _MANIFEST_FIELDS.difference(reader.fieldnames or ())
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"源清单缺少字段：{names}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"源清单不包含样本：{manifest_path}")
    return rows


def _source_path(data_root, relative_path, sample_id, field_name):
    relative = Path(relative_path)
    if relative.is_absolute() or relative.drive:
        raise ValueError(
            f"{sample_id} 的 {field_name} 必须是数据根目录相对路径"
        )
    data_root = Path(data_root).resolve()
    candidate = data_root
    for part in relative.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError(
                f"{sample_id} 的 {field_name} 超出数据根目录：{relative_path}"
            )
        try:
            entries = list(candidate.iterdir())
        except OSError as error:
            raise FileNotFoundError(
                f"{sample_id} 的路径目录不存在：{candidate}"
            ) from error
        exact = [entry for entry in entries if entry.name == part]
        matches = (
            exact
            if exact
            else [
                entry
                for entry in entries
                if entry.name.casefold() == part.casefold()
            ]
        )
        if len(matches) != 1:
            raise FileNotFoundError(
                f"{sample_id} 的文件不存在或路径大小写不唯一："
                f"{data_root / relative}"
            )
        candidate = matches[0]
    candidate = candidate.resolve()
    try:
        candidate.relative_to(data_root)
    except ValueError as error:
        raise ValueError(
            f"{sample_id} 的 {field_name} 超出数据根目录：{relative_path}"
        ) from error
    if not candidate.is_file():
        raise FileNotFoundError(f"{sample_id} 的文件不存在：{candidate}")
    return candidate


def _read_grayscale(path):
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError as error:
        raise ValueError(f"无法读取掩膜：{path}") from error
    image = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"无法读取掩膜：{path}")
    return image


def _write_png(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(
        ".png",
        image,
        [cv2.IMWRITE_PNG_COMPRESSION, 6],
    )
    if not success:
        raise OSError(f"无法编码图像：{path}")
    temporary = path.with_name(f".{path.name}.tmp")
    encoded.tofile(str(temporary))
    temporary.replace(path)


def _output_filename(source_image_path):
    name = Path(source_image_path).name
    return name if Path(name).suffix.lower() == ".png" else f"{name}.png"


def _correct_image(image, ring_result, interpolation):
    height, width = ring_result.corrected.shape[:2]
    return cv2.warpAffine(
        image,
        ring_result.rectification_matrix,
        (width, height),
        flags=interpolation,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def _normalized_remap(
    image,
    ring_result,
    radial_samples,
    interpolation,
):
    angle_samples = len(ring_result.inner_boundary)
    angles = np.linspace(
        0.0,
        2.0 * np.pi,
        angle_samples,
        endpoint=False,
    )
    normalized_radius = np.linspace(
        1.0,
        0.0,
        radial_samples,
        dtype=np.float32,
    )[:, None]
    radii = (
        ring_result.inner_boundary[None, :]
        + normalized_radius
        * (
            ring_result.outer_boundary
            - ring_result.inner_boundary
        )[None, :]
    )
    center = ring_result.corrected_outer_circle
    map_x = center.x + radii * np.cos(angles)[None, :]
    map_y = center.y + radii * np.sin(angles)[None, :]
    return cv2.remap(
        image,
        map_x.astype(np.float32),
        map_y.astype(np.float32),
        interpolation,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def _load_ring_result(
    image_path,
    source_root,
    cache_dir,
    output_size,
    angle_samples,
):
    if cache_dir is None:
        return (
            process_image_path(
                image_path,
                output_size=output_size,
                angle_samples=angle_samples,
            ),
            "disabled",
        )

    from tool_defect.detection.polar_cache import load_or_build_cache

    return load_or_build_cache(
        image_path,
        source_root,
        cache_dir,
        output_size=output_size,
        angle_samples=angle_samples,
        load_source=True,
    )


def _process_pair(
    image_path,
    mask_path,
    mode,
    source_root,
    cache_dir,
    output_size,
    angle_samples,
    radial_samples,
):
    ring_result, cache_state = _load_ring_result(
        image_path,
        source_root,
        cache_dir,
        output_size,
        angle_samples,
    )
    source_mask = _read_grayscale(mask_path)
    if source_mask.shape != ring_result.source.shape[:2]:
        raise ValueError(
            "图像与掩膜尺寸不一致："
            f"{image_path} 为 {ring_result.source.shape[:2]}，"
            f"{mask_path} 为 {source_mask.shape}"
        )
    source_mask = np.where(source_mask > 127, 255, 0).astype(np.uint8)
    corrected_image = _correct_image(
        ring_result.source,
        ring_result,
        cv2.INTER_LINEAR,
    )
    corrected_mask = _correct_image(
        source_mask,
        ring_result,
        cv2.INTER_NEAREST,
    )
    center = (
        ring_result.corrected_outer_circle.x,
        ring_result.corrected_outer_circle.y,
    )

    if mode == "adaptive-annular":
        output_image = extract_adaptive_annular_roi(
            corrected_image,
            center,
            ring_result.inner_boundary,
            ring_result.outer_boundary,
        )
        output_mask = extract_adaptive_annular_roi(
            corrected_mask,
            center,
            ring_result.inner_boundary,
            ring_result.outer_boundary,
        )
    else:
        target_radial_samples = (
            int(radial_samples)
            if radial_samples is not None
            else int(ring_result.polar_image.shape[0])
        )
        if radial_samples is None:
            output_image = ring_result.polar_image.copy()
        else:
            output_image = _normalized_remap(
                corrected_image,
                ring_result,
                target_radial_samples,
                cv2.INTER_LINEAR,
            )
        output_mask = _normalized_remap(
            corrected_mask,
            ring_result,
            target_radial_samples,
            cv2.INTER_NEAREST,
        )

    output_mask = np.where(output_mask > 127, 255, 0).astype(np.uint8)
    if output_image.shape[:2] != output_mask.shape:
        raise RuntimeError(
            "处理后的图像与掩膜尺寸不一致："
            f"{output_image.shape[:2]} 与 {output_mask.shape}"
        )
    return output_image, output_mask, source_mask, cache_state


def _write_provenance(rows, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=_PROVENANCE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def build_ring_dataset(
    source_data_root,
    source_manifest,
    output_root,
    mode,
    *,
    cache_dir=None,
    output_size=512,
    angle_samples=1440,
    radial_samples=None,
    progress_callback=None,
):
    """生成可直接供现有训练加载器使用的图像、掩膜和清单。"""

    if mode not in DATASET_MODES:
        raise ValueError(f"不支持的数据集模式：{mode}")
    output_size = int(output_size)
    angle_samples = int(angle_samples)
    if output_size < 32:
        raise ValueError("output_size 必须至少为 32")
    if angle_samples < 32:
        raise ValueError("angle_samples 必须至少为 32")
    if radial_samples is not None:
        radial_samples = int(radial_samples)
        if mode != "boundary-normalized":
            raise ValueError("radial_samples 仅适用于 boundary-normalized 模式")
        if radial_samples < 2:
            raise ValueError("radial_samples 必须至少为 2")

    source_data_root = Path(source_data_root).resolve()
    source_manifest = Path(source_manifest).resolve()
    output_root = Path(output_root).resolve()
    cache_dir = Path(cache_dir).resolve() if cache_dir is not None else None
    if output_root == source_data_root:
        raise ValueError("输出目录不能与源数据根目录相同")

    source_rows = _read_manifest(source_manifest)
    source_image_root = source_data_root / "images"
    generated_rows = []
    provenance_rows = []
    failures = []
    empty_positive_masks = []
    cache_states = Counter()
    output_paths = set()

    for index, row in enumerate(source_rows, start=1):
        sample_id = row["sample_id"]
        try:
            label_name = row["label_name"]
            if label_name not in {"qualified", "unqualified"}:
                raise ValueError(f"不支持的类别：{label_name}")
            expected_label = 0 if label_name == "qualified" else 1
            if int(row["label"]) != expected_label:
                raise ValueError(
                    f"类别 {label_name} 与标签 {row['label']} 不一致"
                )
            if row["split"] not in {"train", "validation", "test"}:
                raise ValueError(f"不支持的数据划分：{row['split']}")
            image_path = _source_path(
                source_data_root,
                row["image_path"],
                sample_id,
                "image_path",
            )
            mask_path = _source_path(
                source_data_root,
                row["mask_path"],
                sample_id,
                "mask_path",
            )
            filename = _output_filename(row["image_path"])
            output_image_relative = Path("images") / label_name / filename
            output_mask_relative = Path("masks") / label_name / filename
            path_key = output_image_relative.as_posix().lower()
            if path_key in output_paths:
                raise ValueError(
                    f"多个样本映射到同一输出文件：{path_key}"
                )
            output_paths.add(path_key)

            output_image, output_mask, source_mask, cache_state = _process_pair(
                image_path,
                mask_path,
                mode,
                source_image_root,
                cache_dir,
                output_size,
                angle_samples,
                radial_samples,
            )
            _write_png(output_root / output_image_relative, output_image)
            _write_png(output_root / output_mask_relative, output_mask)

            source_foreground = int(np.count_nonzero(source_mask))
            output_foreground = int(np.count_nonzero(output_mask))
            if source_foreground > 0 and output_foreground == 0:
                empty_positive_masks.append(sample_id)
            cache_states[cache_state] += 1
            generated_rows.append(
                ManifestRow(
                    sample_id=sample_id,
                    image_path=output_image_relative.as_posix(),
                    mask_path=output_mask_relative.as_posix(),
                    annotation_path="",
                    label=int(row["label"]),
                    label_name=label_name,
                    split=row["split"],
                )
            )
            provenance_rows.append(
                {
                    "sample_id": sample_id,
                    "source_image_path": row["image_path"],
                    "source_mask_path": row["mask_path"],
                    "source_annotation_path": row["annotation_path"],
                    "output_image_path": output_image_relative.as_posix(),
                    "output_mask_path": output_mask_relative.as_posix(),
                    "label": int(row["label"]),
                    "label_name": label_name,
                    "split": row["split"],
                    "source_height": int(source_mask.shape[0]),
                    "source_width": int(source_mask.shape[1]),
                    "output_height": int(output_mask.shape[0]),
                    "output_width": int(output_mask.shape[1]),
                    "source_foreground_pixels": source_foreground,
                    "source_foreground_fraction": (
                        source_foreground / source_mask.size
                    ),
                    "output_foreground_pixels": output_foreground,
                    "output_foreground_fraction": (
                        output_foreground / output_mask.size
                    ),
                    "cache_state": cache_state,
                }
            )
            if progress_callback is not None:
                progress_callback(index, len(source_rows), sample_id, cache_state)
        except Exception as error:
            failures.append(
                {
                    "sample_id": sample_id,
                    "image_path": row.get("image_path", ""),
                    "message": str(error),
                }
            )

    provenance_path = output_root / "manifests" / "provenance.csv"
    _write_provenance(provenance_rows, provenance_path)
    has_errors = bool(failures or empty_positive_masks)
    report = {
        "status": "failed" if has_errors else "complete",
        "generator_version": GENERATOR_VERSION,
        "mode": mode,
        "source_data_root": str(source_data_root),
        "source_manifest": str(source_manifest),
        "output_root": str(output_root),
        "cache_dir": str(cache_dir) if cache_dir is not None else None,
        "output_size": output_size,
        "angle_samples": angle_samples,
        "radial_samples": radial_samples,
        "input_samples": len(source_rows),
        "generated_samples": len(generated_rows),
        "split_counts": dict(Counter(row.split for row in generated_rows)),
        "label_counts": dict(Counter(row.label_name for row in generated_rows)),
        "cache_states": dict(cache_states),
        "empty_positive_masks": empty_positive_masks,
        "failed_samples": len(failures),
        "failures": failures,
        "manifest": (
            "manifests/dataset.csv"
            if not failures and not empty_positive_masks
            else None
        ),
        "provenance": "manifests/provenance.csv",
    }
    report_path = output_root / "generation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if not has_errors:
        manifest_path = output_root / "manifests" / "dataset.csv"
        write_manifest(generated_rows, manifest_path)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if failures:
        raise RuntimeError(
            f"{len(failures)} 个样本生成失败，详情见：{report_path}"
        )
    if empty_positive_masks:
        raise RuntimeError(
            "处理后存在空的正样本掩膜，未写入训练清单；"
            f"详情见：{report_path}"
        )

    return report
