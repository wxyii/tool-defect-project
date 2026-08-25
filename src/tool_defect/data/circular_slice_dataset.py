"""Generate overlapping circular slices from a boundary-normalized dataset.

The input images are expected to be boundary-normalized polar images whose
second axis is periodic.  A slice therefore uses circular indexing instead of
padding at the 0/360 degree seam.  Classification labels are derived from the
cropped mask: a patch is defective exactly when its binary mask contains at
least ``min_foreground_pixels`` foreground pixels.
"""

from collections import Counter
import csv
import json
from pathlib import Path
import shutil
import tempfile

import cv2
import numpy as np

from tool_defect.data.manifest import ManifestRow, write_manifest


GENERATOR_VERSION = 1
DEFAULT_SLICE_COUNT = 8
DEFAULT_WINDOW_DEGREES = 90.0
DEFAULT_STRIDE_DEGREES = 45.0

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
    "parent_sample_id",
    "parent_image_path",
    "parent_mask_path",
    "parent_annotation_path",
    "output_image_path",
    "output_mask_path",
    "parent_label",
    "parent_label_name",
    "label",
    "label_name",
    "split",
    "patch_index",
    "start_angle_degrees",
    "end_angle_degrees",
    "wraps_seam",
    "source_height",
    "source_width",
    "output_height",
    "output_width",
    "foreground_pixels",
    "foreground_fraction",
    "min_foreground_pixels",
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


def _resolve_source_path(data_root, relative_path, sample_id, field_name):
    relative = Path(relative_path)
    if not relative_path or relative.is_absolute() or relative.drive:
        raise ValueError(
            f"{sample_id} 的 {field_name} 必须是数据根目录相对路径"
        )
    data_root = Path(data_root).resolve()
    candidate = (data_root / relative).resolve()
    try:
        candidate.relative_to(data_root)
    except ValueError as error:
        raise ValueError(
            f"{sample_id} 的 {field_name} 超出数据根目录：{relative_path}"
        ) from error
    if not candidate.is_file():
        raise FileNotFoundError(f"{sample_id} 的文件不存在：{candidate}")
    return candidate


def _read_image(path):
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError as error:
        raise ValueError(f"无法读取图像：{path}") from error
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图像：{path}")
    return image


def _read_mask(path):
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError as error:
        raise ValueError(f"无法读取掩膜：{path}") from error
    mask = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise ValueError(f"无法读取掩膜：{path}")
    return np.where(mask > 127, 255, 0).astype(np.uint8)


def _write_png(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(
        ".png",
        image,
        [cv2.IMWRITE_PNG_COMPRESSION, 6],
    )
    if not success:
        raise OSError(f"无法编码 PNG：{path}")
    temporary = path.with_name(f".{path.name}.tmp")
    encoded.tofile(str(temporary))
    temporary.replace(path)


def _validate_geometry(
    width,
    slice_count,
    window_degrees,
    stride_degrees,
):
    width = int(width)
    slice_count = int(slice_count)
    window_degrees = float(window_degrees)
    stride_degrees = float(stride_degrees)
    if width < 1:
        raise ValueError("圆周轴宽度必须为正数")
    if slice_count < 1:
        raise ValueError("slice_count 必须为正数")
    if not 0 < stride_degrees <= 360:
        raise ValueError("stride_degrees 必须位于 (0, 360] 范围内")
    if not 0 < window_degrees <= 360:
        raise ValueError("window_degrees 必须位于 (0, 360] 范围内")
    if not np.isclose(slice_count * stride_degrees, 360.0):
        raise ValueError(
            "slice_count * stride_degrees 必须等于 360 度，才能覆盖完整圆周"
        )
    if window_degrees < stride_degrees:
        raise ValueError(
            "window_degrees 必须不小于 stride_degrees，才能形成重叠或无重叠切片"
        )

    stride_columns = width * stride_degrees / 360.0
    window_columns = width * window_degrees / 360.0
    rounded_stride = round(stride_columns)
    rounded_window = round(window_columns)
    if not np.isclose(stride_columns, rounded_stride):
        raise ValueError(
            f"stride_degrees={stride_degrees} 无法在宽度 {width} 上转换为整数列"
        )
    if not np.isclose(window_columns, rounded_window):
        raise ValueError(
            f"window_degrees={window_degrees} 无法在宽度 {width} 上转换为整数列"
        )
    if rounded_stride < 1 or rounded_window < 1:
        raise ValueError("切片宽度换算后必须至少为 1 列")
    return rounded_stride, rounded_window


def circular_slice(array, start_column, width):
    """Take a periodic slice along axis 1 without seam padding."""

    array = np.asarray(array)
    if array.ndim not in (2, 3):
        raise ValueError("array 必须是 HxW 或 HxWxC")
    source_width = array.shape[1]
    start_column = int(start_column)
    width = int(width)
    if source_width < 1 or width < 1:
        raise ValueError("源宽度和切片宽度必须为正数")
    columns = (np.arange(start_column, start_column + width) % source_width).astype(
        np.intp
    )
    return np.take(array, columns, axis=1)


def _patch_filename(source_path, patch_index, parent_label_name):
    source_name = Path(source_path).name
    stem = Path(source_name).stem
    return f"{parent_label_name}__{stem}__patch_{patch_index:02d}.png"


def _patch_sample_id(
    label_name,
    source_path,
    patch_index,
    parent_label_name,
):
    return f"{label_name}/{_patch_filename(source_path, patch_index, parent_label_name)}"


def _write_provenance(rows, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=_PROVENANCE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _assert_output_is_safe(source_root, output_root):
    source_root = Path(source_root).resolve()
    output_root = Path(output_root).resolve()
    if output_root == source_root:
        raise ValueError("输出目录不能与源数据根目录相同")
    try:
        output_root.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise ValueError("输出目录不能位于源数据根目录内部")
    try:
        source_root.relative_to(output_root)
    except ValueError:
        pass
    else:
        raise ValueError("源数据根目录不能位于输出目录内部")
    if output_root.exists():
        raise FileExistsError(
            f"输出目录已存在，为避免覆盖已有数据请更换路径：{output_root}"
        )


def build_circular_slice_dataset(
    source_data_root,
    source_manifest,
    output_root,
    *,
    slice_count=DEFAULT_SLICE_COUNT,
    window_degrees=DEFAULT_WINDOW_DEGREES,
    stride_degrees=DEFAULT_STRIDE_DEGREES,
    min_foreground_pixels=1,
    progress_callback=None,
):
    """Build an overlap-aware child manifest from a boundary-normalized set.

    The source split is assigned at parent-image level and copied to all child
    patches.  This preserves the source experiment's held-out test set while
    preventing sibling patches from crossing split boundaries.
    """

    slice_count = int(slice_count)
    min_foreground_pixels = int(min_foreground_pixels)
    if min_foreground_pixels < 1:
        raise ValueError("min_foreground_pixels 必须至少为 1")

    source_data_root = Path(source_data_root).resolve()
    source_manifest = Path(source_manifest).resolve()
    output_root = Path(output_root).resolve()
    _assert_output_is_safe(source_data_root, output_root)
    source_rows = _read_manifest(source_manifest)

    seen_parent_ids = set()
    seen_output_paths = set()
    generated_rows = []
    provenance_rows = []
    failures = []
    source_shape = None
    patch_shape = None
    patch_label_counts = Counter()
    split_label_counts = Counter()
    parent_split_counts = Counter()
    zero_foreground_patches = []
    small_foreground_patches = []

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{output_root.name}.tmp-",
            dir=str(output_root.parent),
        )
    )
    preserve_staging = False
    try:
        for index, row in enumerate(source_rows, start=1):
            sample_id = row["sample_id"]
            try:
                if sample_id in seen_parent_ids:
                    raise ValueError(f"源清单包含重复 sample_id：{sample_id}")
                seen_parent_ids.add(sample_id)

                parent_label_name = row["label_name"]
                if parent_label_name not in {"qualified", "unqualified"}:
                    raise ValueError(f"不支持的父图类别：{parent_label_name}")
                parent_label = int(row["label"])
                expected_parent_label = (
                    0 if parent_label_name == "qualified" else 1
                )
                if parent_label != expected_parent_label:
                    raise ValueError(
                        f"父图类别 {parent_label_name} 与标签 {parent_label} 不一致"
                    )
                split = row["split"]
                if split not in {"train", "validation", "test"}:
                    raise ValueError(f"不支持的数据划分：{split}")

                image_path = _resolve_source_path(
                    source_data_root,
                    row["image_path"],
                    sample_id,
                    "image_path",
                )
                mask_path = _resolve_source_path(
                    source_data_root,
                    row["mask_path"],
                    sample_id,
                    "mask_path",
                )
                image = _read_image(image_path)
                mask = _read_mask(mask_path)
                if image.shape[:2] != mask.shape:
                    raise ValueError(
                        "图像与掩膜尺寸不一致："
                        f"{image_path} 为 {image.shape[:2]}，"
                        f"{mask_path} 为 {mask.shape}"
                    )
                current_shape = tuple(int(value) for value in mask.shape)
                if source_shape is None:
                    source_shape = current_shape
                elif current_shape != source_shape:
                    raise ValueError(
                        "边界归一化数据集中的图像尺寸不一致："
                        f"期望 {source_shape}，实际 {current_shape}（{sample_id}）"
                    )

                stride_columns, window_columns = _validate_geometry(
                    image.shape[1],
                    slice_count,
                    window_degrees,
                    stride_degrees,
                )
                for patch_index in range(slice_count):
                    start_column = patch_index * stride_columns
                    patch_image = circular_slice(
                        image,
                        start_column,
                        window_columns,
                    )
                    patch_mask = circular_slice(
                        mask,
                        start_column,
                        window_columns,
                    )
                    patch_mask = np.where(patch_mask > 127, 255, 0).astype(
                        np.uint8
                    )
                    foreground_pixels = int(np.count_nonzero(patch_mask))
                    patch_label = int(
                        foreground_pixels >= min_foreground_pixels
                    )
                    patch_label_name = (
                        "unqualified" if patch_label else "qualified"
                    )
                    patch_name = _patch_filename(
                        row["image_path"],
                        patch_index,
                        parent_label_name,
                    )
                    output_image_relative = (
                        Path("images") / patch_label_name / patch_name
                    )
                    output_mask_relative = (
                        Path("masks") / patch_label_name / patch_name
                    )
                    output_key = output_image_relative.as_posix().casefold()
                    if output_key in seen_output_paths:
                        raise ValueError(
                            f"多个子图映射到同一输出文件：{output_key}"
                        )
                    seen_output_paths.add(output_key)

                    _write_png(
                        staging_root / output_image_relative,
                        patch_image,
                    )
                    _write_png(
                        staging_root / output_mask_relative,
                        patch_mask,
                    )

                    child_sample_id = _patch_sample_id(
                        patch_label_name,
                        row["image_path"],
                        patch_index,
                        parent_label_name,
                    )
                    generated_rows.append(
                        ManifestRow(
                            sample_id=child_sample_id,
                            image_path=output_image_relative.as_posix(),
                            mask_path=output_mask_relative.as_posix(),
                            annotation_path="",
                            label=patch_label,
                            label_name=patch_label_name,
                            split=split,
                        )
                    )
                    patch_label_counts[patch_label_name] += 1
                    split_label_counts[(split, patch_label_name)] += 1
                    provenance_rows.append(
                        {
                            "sample_id": child_sample_id,
                            "parent_sample_id": sample_id,
                            "parent_image_path": row["image_path"],
                            "parent_mask_path": row["mask_path"],
                            "parent_annotation_path": row[
                                "annotation_path"
                            ],
                            "output_image_path": output_image_relative.as_posix(),
                            "output_mask_path": output_mask_relative.as_posix(),
                            "parent_label": parent_label,
                            "parent_label_name": parent_label_name,
                            "label": patch_label,
                            "label_name": patch_label_name,
                            "split": split,
                            "patch_index": patch_index,
                            "start_angle_degrees": round(
                                patch_index * stride_degrees,
                                6,
                            ),
                            "end_angle_degrees": round(
                                patch_index * stride_degrees + window_degrees,
                                6,
                            ),
                            "wraps_seam": str(
                                patch_index * stride_degrees + window_degrees
                                > 360.0
                            ).lower(),
                            "source_height": current_shape[0],
                            "source_width": current_shape[1],
                            "output_height": int(patch_mask.shape[0]),
                            "output_width": int(patch_mask.shape[1]),
                            "foreground_pixels": foreground_pixels,
                            "foreground_fraction": (
                                foreground_pixels / patch_mask.size
                            ),
                            "min_foreground_pixels": min_foreground_pixels,
                        }
                    )
                    if foreground_pixels == 0:
                        zero_foreground_patches.append(child_sample_id)
                    elif foreground_pixels < 10:
                        small_foreground_patches.append(child_sample_id)
                    if patch_shape is None:
                        patch_shape = tuple(
                            int(value) for value in patch_mask.shape
                        )

                parent_split_counts[split] += 1
                if progress_callback is not None:
                    progress_callback(
                        index,
                        len(source_rows),
                        sample_id,
                        slice_count,
                    )
            except Exception as error:
                failures.append(
                    {
                        "sample_id": sample_id,
                        "image_path": row.get("image_path", ""),
                        "message": str(error),
                    }
                )

        report = {
            "status": "failed" if failures else "complete",
            "generator_version": GENERATOR_VERSION,
            "mode": "boundary-normalized-circular-overlap",
            "source_data_root": str(source_data_root),
            "source_manifest": str(source_manifest),
            "output_root": str(output_root),
            "slice_count": slice_count,
            "window_degrees": float(window_degrees),
            "stride_degrees": float(stride_degrees),
            "min_foreground_pixels": min_foreground_pixels,
            "input_parent_samples": len(source_rows),
            "generated_samples": len(generated_rows),
            "patches_per_parent": slice_count,
            "source_shape": list(source_shape) if source_shape else None,
            "patch_shape": list(patch_shape) if patch_shape else None,
            "parent_split_counts": dict(parent_split_counts),
            "split_label_counts": {
                f"{split}/{label_name}": count
                for (split, label_name), count in sorted(
                    split_label_counts.items()
                )
            },
            "patch_label_counts": dict(patch_label_counts),
            "zero_foreground_patch_count": len(zero_foreground_patches),
            "small_foreground_patch_count": len(small_foreground_patches),
            "small_foreground_patch_ids": small_foreground_patches,
            "failed_samples": len(failures),
            "failures": failures,
            "manifest": (
                "manifests/dataset.csv" if not failures else None
            ),
            "provenance": "manifests/provenance.csv",
        }
        report_path = staging_root / "generation_report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_provenance(
            provenance_rows,
            staging_root / "manifests" / "provenance.csv",
        )

        if failures:
            preserve_staging = True
            staging_root.replace(output_root)
            raise RuntimeError(
                f"{len(failures)} 个父样本生成失败，详情见："
                f"{output_root / 'generation_report.json'}"
            )

        write_manifest(
            generated_rows,
            staging_root / "manifests" / "dataset.csv",
        )
        staging_root.replace(output_root)
        preserve_staging = True
        return report
    finally:
        if staging_root.exists() and not preserve_staging:
            shutil.rmtree(staging_root)
