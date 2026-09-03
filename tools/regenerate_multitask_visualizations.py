#!/usr/bin/env python3
"""从已有多任务评估结果重新生成生产现场可视化图片。"""

import argparse
import csv
from pathlib import Path
import sys

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tool_defect.inference.visualize import (  # noqa: E402
    overlay_defect_on_image,
    restore_normalized_mask_to_circle,
)


BOUNDARY_DATASET = "boundary_normalized"
BOUNDARY_PATCH_DATASET = "boundary_normalized_8patch"
BOUNDARY_PROVENANCE = (
    Path("data")
    / "processed"
    / BOUNDARY_DATASET
    / "manifests"
    / "provenance.csv"
)
CACHE_RELATIVE_PATH = Path("outputs") / "polar_cache"
CIRCULAR_OUTPUT_SIZE = 512
CIRCULAR_ANGLE_SAMPLES = 1440

DATASET_OUTPUTS = (
    ("raw", "visualizations_clean"),
    ("adaptive_annular", "visualizations_clean"),
    (BOUNDARY_DATASET, "visualizations_circular"),
    ("adaptive_annular_8patch", "visualizations_clean"),
    (BOUNDARY_PATCH_DATASET, "visualizations_circular"),
)


def _read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _safe_relative_path(root, relative_path, description):
    relative = Path(relative_path)
    if not relative_path or relative.is_absolute() or relative.drive:
        raise ValueError(f"{description} 必须是数据根目录相对路径：{relative_path}")
    root = Path(root).resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{description} 超出数据根目录：{relative_path}") from error
    if not candidate.is_file():
        raise FileNotFoundError(f"{description} 不存在：{candidate}")
    return candidate


def _read_color_image(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"图像不存在：{path}")
    encoded = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图像：{path}")
    return image


def _read_binary_mask(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"掩码不存在：{path}")
    encoded = np.fromfile(str(path), dtype=np.uint8)
    mask = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise ValueError(f"无法读取掩码：{path}")
    return np.where(mask > 127, 255, 0).astype(np.uint8)


def _read_boundary_provenance(project_root):
    path = (Path(project_root) / BOUNDARY_PROVENANCE).resolve()
    rows = _read_csv(path)
    if not rows:
        raise ValueError(f"边界归一化溯源清单为空：{path}")
    required = {"sample_id", "source_image_path"}
    missing = required.difference(rows[0])
    if missing:
        raise ValueError(f"边界归一化溯源清单缺少字段：{sorted(missing)}")
    result = {}
    for row in rows:
        sample_id = row.get("sample_id", "")
        if not sample_id:
            raise ValueError(f"边界归一化溯源清单存在空 sample_id：{path}")
        if sample_id in result:
            raise ValueError(f"边界归一化溯源清单存在重复 sample_id：{sample_id}")
        result[sample_id] = row
    return result


def _restore_boundary_display(project_root, sample_id, mask, provenance):
    from tool_defect.detection.polar_cache import load_or_build_cache

    project_root = Path(project_root).resolve()
    data_root = project_root / "data"
    source_root = data_root / "images"
    cache_dir = project_root / CACHE_RELATIVE_PATH
    metadata = provenance.get(sample_id)
    if metadata is None:
        raise KeyError(f"找不到样本的边界归一化溯源信息：{sample_id}")
    source_path = _safe_relative_path(
        data_root,
        metadata["source_image_path"],
        f"{sample_id} 的原始图像",
    )
    ring_result, cache_state = load_or_build_cache(
        source_path,
        source_root,
        cache_dir,
        output_size=CIRCULAR_OUTPUT_SIZE,
        angle_samples=CIRCULAR_ANGLE_SAMPLES,
        load_source=True,
    )
    corrected_height, corrected_width = ring_result.corrected.shape[:2]
    if (corrected_height, corrected_width) != (
        CIRCULAR_OUTPUT_SIZE,
        CIRCULAR_OUTPUT_SIZE,
    ):
        raise ValueError(
            f"{sample_id} 的校正图尺寸异常："
            f"{(corrected_height, corrected_width)}"
        )
    corrected = cv2.warpAffine(
        ring_result.source,
        ring_result.rectification_matrix,
        (corrected_width, corrected_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    center = (
        ring_result.corrected_outer_circle.x,
        ring_result.corrected_outer_circle.y,
    )
    restored_mask = restore_normalized_mask_to_circle(
        mask,
        ring_result.inner_boundary,
        ring_result.outer_boundary,
        (corrected_height, corrected_width),
        center=center,
    )
    return corrected, restored_mask, cache_state


def _confidence(row):
    try:
        qualified = float(row["qualified_probability"])
        unqualified = float(row["unqualified_probability"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"分类概率字段无效：{row.get('sample_id', '<unknown>')}") from error
    confidence = max(qualified, unqualified)
    if not np.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError(f"分类置信度无效：{row.get('sample_id', '<unknown>')}")
    return confidence


def regenerate_dataset_visualizations(
    project_root,
    suite_root,
    dataset_id,
    output_name,
    *,
    min_component_area=12,
    max_dimension=1600,
    provenance=None,
):
    result_dir = (Path(suite_root) / dataset_id).resolve()
    predictions_path = result_dir / "predictions.csv"
    if not predictions_path.is_file():
        raise FileNotFoundError(f"评估结果清单不存在：{predictions_path}")
    rows = _read_csv(predictions_path)
    if not rows:
        raise ValueError(f"评估结果清单为空：{predictions_path}")
    required = {
        "sample_id",
        "image_path",
        "predicted_class",
        "qualified_probability",
        "unqualified_probability",
        "mask_path",
        "visualization_path",
    }
    missing = required.difference(rows[0])
    if missing:
        raise ValueError(f"评估结果清单缺少字段：{sorted(missing)}")

    output_dir = result_dir / output_name
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_states = {}
    output_paths = []
    for row in rows:
        sample_id = row["sample_id"]
        mask_path = (result_dir / row["mask_path"]).resolve()
        mask = _read_binary_mask(mask_path)
        if dataset_id in {BOUNDARY_DATASET, BOUNDARY_PATCH_DATASET}:
            display_image, display_mask, cache_state = _restore_boundary_display(
                project_root,
                sample_id,
                mask,
                provenance,
            )
            cache_states[cache_state] = cache_states.get(cache_state, 0) + 1
            original_path = None
        else:
            image_path = Path(row["image_path"])
            if not image_path.is_absolute():
                image_path = result_dir / image_path
            display_image = _read_color_image(image_path)
            display_mask = mask
            original_path = None

        output_path = output_dir / Path(row["visualization_path"]).name
        overlay_defect_on_image(
            original_path=original_path,
            original_image=display_image,
            defect_mask=display_mask,
            predicted_class=row["predicted_class"],
            confidence=_confidence(row),
            output_path=output_path,
            min_component_area=min_component_area,
            max_dimension=max_dimension,
        )
        output_paths.append(output_path)

    return {
        "dataset_id": dataset_id,
        "source_results": str(result_dir),
        "output_dir": str(output_dir),
        "samples": len(rows),
        "generated": len(output_paths),
        "cache_states": cache_states,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description="使用已有五类模型测试结果生成生产现场可视化图片。"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="项目根目录，默认是当前脚本所在项目。",
    )
    parser.add_argument(
        "--suite-root",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "multitask_suite",
        help="已有多任务评估结果目录。",
    )
    parser.add_argument(
        "--min-component-area",
        type=int,
        default=12,
        help="忽略小于该像素面积的预测连通区域。",
    )
    parser.add_argument(
        "--max-dimension",
        type=int,
        default=1600,
        help="生成图片的最大边长。",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    project_root = args.project_root.resolve()
    suite_root = args.suite_root
    if not suite_root.is_absolute():
        suite_root = project_root / suite_root
    suite_root = suite_root.resolve()
    if args.min_component_area < 1:
        raise SystemExit("--min-component-area 必须为正数")
    if args.max_dimension < 256:
        raise SystemExit("--max-dimension 必须至少为 256")

    boundary_provenance = _read_boundary_provenance(project_root)
    summaries = []
    for dataset_id, output_name in DATASET_OUTPUTS:
        summary = regenerate_dataset_visualizations(
            project_root,
            suite_root,
            dataset_id,
            output_name,
            min_component_area=args.min_component_area,
            max_dimension=args.max_dimension,
            provenance=boundary_provenance,
        )
        summaries.append(summary)
        print(
            f"{dataset_id}：生成 {summary['generated']}/{summary['samples']} 张，"
            f"输出到 {summary['output_dir']}"
        )
    print("五类生产现场可视化图片生成完成，未重新训练或重新推理模型。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
