"""利用刀片圆周重复结构进行无标签极坐标异常检测。"""

from dataclasses import asdict, dataclass
import csv
import json
from pathlib import Path
from typing import Iterable, Optional

import cv2
import numpy as np

from tool_defect.data.ring_geometry import (
    RingResult,
    process_image_path,
    read_color_image,
)


MODEL_VERSION = 1
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
FEATURE_NAMES = ("texture", "gradient", "boundary")


@dataclass(frozen=True)
class PolarAnomalyModel:
    """无标签标定得到的特征尺度和候选区域阈值。"""

    version: int
    feature_centers: tuple
    feature_scales: tuple
    threshold: float
    output_size: int = 512
    angle_samples: int = 1440
    minimum_periods: int = 8
    maximum_periods: int = 40
    calibration_images: int = 0
    failed_images: int = 0

    def save(self, path) -> Path:
        path = Path(path)
        if path.suffix.lower() != ".json":
            path = path / "polar_anomaly.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["feature_names"] = list(FEATURE_NAMES)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.is_dir():
            path = path / "polar_anomaly.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("version", -1)) != MODEL_VERSION:
            raise ValueError(f"不支持的极坐标异常模型版本：{payload.get('version')}")
        names = tuple(payload.pop("feature_names", FEATURE_NAMES))
        if names != FEATURE_NAMES:
            raise ValueError("模型特征顺序与当前程序不兼容")
        payload["feature_centers"] = tuple(payload["feature_centers"])
        payload["feature_scales"] = tuple(payload["feature_scales"])
        return cls(**payload)


@dataclass(frozen=True)
class DefectRegion:
    """一个疑似异常区域，径向位置零表示外缘、一表示内缘。"""

    region_id: int
    start_angle_degrees: float
    end_angle_degrees: float
    radial_start: float
    radial_end: float
    area: int
    peak_score: float
    mean_score: float


@dataclass
class DetectionResult:
    """单张刀片的异常检测结果和可审计中间量。"""

    image_path: Path
    status: str
    message: str
    anomaly_score: float
    threshold: float
    period_count: int
    phase_offset: int
    regions: list
    ring_result: Optional[RingResult] = None
    feature_maps: Optional[np.ndarray] = None
    anomaly_map: Optional[np.ndarray] = None
    candidate_mask: Optional[np.ndarray] = None


@dataclass
class _PolarAnalysis:
    period_count: int
    phase_offset: int
    feature_maps: np.ndarray


def iter_image_paths(input_path) -> list:
    """按路径排序发现图像；父目录名称不会进入任何特征。"""

    input_path = Path(input_path)
    if input_path.is_file():
        if input_path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"不支持的图像格式：{input_path}")
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"输入路径不存在：{input_path}")
    return sorted(
        path
        for path in input_path.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def _robust_location_scale(values):
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if not len(values):
        return 0.0, 1.0
    retained = values
    for _ in range(2):
        limit = float(np.quantile(retained, 0.95))
        retained = retained[retained <= limit]
        if len(retained) < 32:
            retained = values
            break
    center = float(np.median(retained))
    scale = float(1.4826 * np.median(np.abs(retained - center)))
    if scale < 1e-4:
        scale = max(float(np.std(retained)), 1e-4)
    return center, scale


def _normalize_polar(polar_image):
    gray = cv2.cvtColor(polar_image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    row_median = np.median(gray, axis=1, keepdims=True)
    row_mad = 1.4826 * np.median(
        np.abs(gray - row_median), axis=1, keepdims=True
    )
    normalized = (gray - row_median) / np.maximum(row_mad, 3.0)
    illumination = cv2.GaussianBlur(
        normalized, (0, 0), sigmaX=9.0, sigmaY=2.0
    )
    return np.clip(normalized - illumination, -6.0, 6.0)


def estimate_period_count(
    normalized,
    minimum_periods=8,
    maximum_periods=40,
):
    """以频谱能量、移位相关性和谐波一致性估计圆周重复次数。"""

    height, width = normalized.shape
    if width < minimum_periods * 3:
        raise ValueError("极坐标展开图角度采样数不足")
    upper = min(maximum_periods, width // 3)
    if upper < minimum_periods:
        raise ValueError("无法在指定范围内估计重复周期")

    gradient_x = cv2.Sobel(normalized, cv2.CV_32F, 1, 0, ksize=3)
    start = max(0, int(round(height * 0.05)))
    stop = max(start + 1, int(round(height * 0.82)))
    signal = np.mean(np.abs(gradient_x[start:stop]), axis=0)
    signal = signal - np.mean(signal)
    scale = float(np.linalg.norm(signal))
    if scale < 1e-6:
        raise ValueError("展开图缺少可用于周期估计的结构")
    spectrum = np.abs(np.fft.rfft(signal))
    spectrum /= max(float(np.max(spectrum[minimum_periods : upper + 1])), 1e-6)

    scores = []
    normalized_signal = signal / scale
    for count in range(minimum_periods, upper + 1):
        shift = max(1, int(round(width / count)))
        correlation = float(
            np.dot(normalized_signal, np.roll(normalized_signal, shift))
        )
        harmonic = 0.0
        if count * 2 < len(spectrum):
            harmonic = float(spectrum[count * 2])
        score = (
            0.55 * float(spectrum[count])
            + 0.35 * max(correlation, 0.0)
            + 0.10 * harmonic
        )
        scores.append((score, count))
    best_score, best_count = max(scores)
    if best_score < 0.12:
        raise ValueError("圆周重复结构置信度过低")
    return int(best_count)


def _aligned_period_patches(image, period_count):
    """寻找最低周期离散度的相位，并返回对齐后的周期片段。"""

    height, width = image.shape
    period_width = max(3, int(round(width / period_count)))
    used_width = period_width * period_count
    if used_width > width:
        period_width = width // period_count
        used_width = period_width * period_count
    best = None
    for offset in range(period_width):
        rolled = np.roll(image, -offset, axis=1)[:, :used_width]
        patches = rolled.reshape(height, period_count, period_width)
        patches = np.transpose(patches, (1, 0, 2))
        template = np.median(patches, axis=0)
        dispersion = float(np.median(np.abs(patches - template)))
        if best is None or dispersion < best[0]:
            best = (dispersion, offset, patches)
    return best[1], best[2], used_width


def _leave_one_out_residuals(patches):
    count = len(patches)
    if count < 3:
        raise ValueError("重复周期数量不足以建立图内参照")
    texture = np.empty_like(patches, dtype=np.float32)
    gradient = np.empty_like(patches, dtype=np.float32)
    patch_gradients = np.stack(
        [
            cv2.magnitude(
                cv2.Sobel(patch, cv2.CV_32F, 1, 0, ksize=3),
                cv2.Sobel(patch, cv2.CV_32F, 0, 1, ksize=3),
            )
            for patch in patches
        ]
    )
    for index in range(count):
        others = np.concatenate(
            [patches[:index], patches[index + 1 :]], axis=0
        )
        gradient_others = np.concatenate(
            [patch_gradients[:index], patch_gradients[index + 1 :]], axis=0
        )
        texture[index] = np.abs(
            patches[index] - np.median(others, axis=0)
        )
        gradient[index] = np.abs(
            patch_gradients[index] - np.median(gradient_others, axis=0)
        )
    return texture, gradient


def _patches_to_polar(patches, offset, full_width):
    count, height, period_width = patches.shape
    aligned = np.transpose(patches, (1, 0, 2)).reshape(
        height, count * period_width
    )
    if aligned.shape[1] < full_width:
        padding = full_width - aligned.shape[1]
        aligned = np.pad(aligned, ((0, 0), (0, padding)), mode="wrap")
    return np.roll(aligned[:, :full_width], offset, axis=1)


def analyze_ring_result(
    ring_result,
    minimum_periods=8,
    maximum_periods=40,
):
    normalized = _normalize_polar(ring_result.polar_image)
    period_count = estimate_period_count(
        normalized,
        minimum_periods=minimum_periods,
        maximum_periods=maximum_periods,
    )
    phase_offset, patches, _ = _aligned_period_patches(
        normalized, period_count
    )
    texture_patches, gradient_patches = _leave_one_out_residuals(patches)
    texture = _patches_to_polar(
        texture_patches, phase_offset, normalized.shape[1]
    )
    gradient = _patches_to_polar(
        gradient_patches, phase_offset, normalized.shape[1]
    )

    edge_residual = np.abs(
        ring_result.raw_outer_boundary - ring_result.outer_boundary
    ).astype(np.float32)
    height = normalized.shape[0]
    outer_rows = max(3, int(round(height * 0.28)))
    radial_weight = np.zeros((height, 1), dtype=np.float32)
    radial_weight[:outer_rows, 0] = np.linspace(
        1.0, 0.15, outer_rows, dtype=np.float32
    )
    # 保留校正图中的实际像素偏差，只在多图标定阶段统一缩放。
    # 若先在单图内除以极小的平坦边界方差，普通跟踪抖动会被放大数百倍。
    boundary = radial_weight * edge_residual[None, :]
    feature_maps = np.stack([texture, gradient, boundary]).astype(np.float32)
    return _PolarAnalysis(
        period_count=period_count,
        phase_offset=phase_offset,
        feature_maps=feature_maps,
    )


def _sample_feature_tuples(feature_maps, maximum_samples=5000):
    flattened = feature_maps.reshape(feature_maps.shape[0], -1).T
    step = max(1, int(np.ceil(len(flattened) / maximum_samples)))
    return flattened[::step][:maximum_samples]


def fit_unlabeled_model(
    input_path,
    output_path,
    *,
    output_size=512,
    angle_samples=1440,
    minimum_periods=8,
    maximum_periods=40,
):
    """从无标签图像集合标定特征尺度和候选阈值。"""

    image_paths = iter_image_paths(input_path)
    if not image_paths:
        raise ValueError("输入目录中没有可用图像")
    samples = []
    failures = []
    periods = []
    for image_path in image_paths:
        try:
            ring_result = process_image_path(
                image_path,
                output_size=output_size,
                angle_samples=angle_samples,
            )
            analysis = analyze_ring_result(
                ring_result,
                minimum_periods=minimum_periods,
                maximum_periods=maximum_periods,
            )
            samples.append(_sample_feature_tuples(analysis.feature_maps))
            periods.append(analysis.period_count)
        except Exception as error:
            failures.append((image_path, str(error)))
    if not samples:
        raise RuntimeError("所有图像均无法用于无标签标定")

    sample_matrix = np.concatenate(samples, axis=0)
    centers = []
    scales = []
    for index in range(sample_matrix.shape[1]):
        values = sample_matrix[:, index]
        if index == 2:
            positive = values[values > 1e-4]
            if len(positive) >= 32:
                values = positive
        center, scale = _robust_location_scale(values)
        centers.append(center)
        scales.append(scale)
    robust_scales = np.asarray(scales, dtype=np.float64)
    standardized = np.maximum(
        (sample_matrix - np.asarray(centers)[None, :])
        / robust_scales[None, :],
        0.0,
    )
    # 每个通道的尾部分布不同。以各自的高分位数校准尺度，使纹理、
    # 梯度和边界任一通道都能独立越过同一个阈值，避免边界尖峰抬高
    # 全局阈值后掩盖纹理异常。
    threshold = 6.0
    tail_levels = np.quantile(standardized, 0.995, axis=0)
    tail_factors = np.maximum(tail_levels / threshold, 1.0)
    calibrated_scales = robust_scales * tail_factors
    scales = calibrated_scales.tolist()
    model = PolarAnomalyModel(
        version=MODEL_VERSION,
        feature_centers=tuple(float(value) for value in centers),
        feature_scales=tuple(float(value) for value in scales),
        threshold=threshold,
        output_size=output_size,
        angle_samples=angle_samples,
        minimum_periods=minimum_periods,
        maximum_periods=maximum_periods,
        calibration_images=len(samples),
        failed_images=len(failures),
    )
    model_path = model.save(output_path)
    report = {
        "model_path": str(model_path),
        "input_images": len(image_paths),
        "calibration_images": len(samples),
        "failed_images": len(failures),
        "period_counts": {
            str(count): int(periods.count(count))
            for count in sorted(set(periods))
        },
        "threshold": threshold,
        "feature_centers": dict(zip(FEATURE_NAMES, centers)),
        "feature_scales": dict(zip(FEATURE_NAMES, scales)),
        "robust_feature_scales": dict(
            zip(FEATURE_NAMES, robust_scales.tolist())
        ),
        "tail_scale_factors": dict(
            zip(FEATURE_NAMES, tail_factors.tolist())
        ),
        "failures": [
            {"path": str(path), "message": message}
            for path, message in failures
        ],
    }
    report_path = model_path.parent / "calibration_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return model, report


def _standardize_features(feature_maps, model):
    centers = np.asarray(model.feature_centers, dtype=np.float32)[:, None, None]
    scales = np.asarray(model.feature_scales, dtype=np.float32)[:, None, None]
    standardized = np.maximum((feature_maps - centers) / scales, 0.0)
    fused = np.max(standardized, axis=0)
    return cv2.GaussianBlur(fused, (3, 3), 0.7)


def _circular_components(mask, score_map, minimum_area):
    """在最低占用角度处切开圆周，再做连通域，避免零度接缝断裂。"""

    cut = int(np.argmin(np.sum(mask, axis=0)))
    rolled_mask = np.roll(mask, -cut, axis=1)
    rolled_scores = np.roll(score_map, -cut, axis=1)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        rolled_mask.astype(np.uint8), connectivity=8
    )
    components = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < minimum_area:
            continue
        ys, xs = np.where(labels == label)
        original_xs = np.mod(xs + cut, mask.shape[1])
        component_mask = np.zeros(mask.shape, dtype=np.uint8)
        component_mask[ys, original_xs] = 1
        components.append(
            (
                component_mask,
                ys,
                original_xs,
                rolled_scores[ys, xs],
            )
        )
    return components


def _minimal_circular_interval(columns, width):
    unique = np.unique(columns)
    if len(unique) == width:
        return 0, width - 1
    gaps = np.diff(np.r_[unique, unique[0] + width])
    gap_index = int(np.argmax(gaps))
    start = int(unique[(gap_index + 1) % len(unique)])
    end = int(unique[gap_index])
    return start, end


def _regions_from_map(score_map, threshold):
    mask = (score_map >= threshold).astype(np.uint8)
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8)
    )
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, np.ones((3, 5), dtype=np.uint8)
    )
    minimum_area = max(8, int(round(mask.size * 0.00012)))
    components = _circular_components(mask, score_map, minimum_area)
    regions = []
    retained = np.zeros_like(mask)
    height, width = mask.shape
    for region_index, (component_mask, ys, xs, scores) in enumerate(
        components, start=1
    ):
        retained |= component_mask
        start, end = _minimal_circular_interval(xs, width)
        regions.append(
            DefectRegion(
                region_id=region_index,
                start_angle_degrees=360.0 * start / width,
                end_angle_degrees=360.0 * ((end + 1) % width) / width,
                radial_start=float(np.min(ys) / max(height - 1, 1)),
                radial_end=float(np.max(ys) / max(height - 1, 1)),
                area=int(len(ys)),
                peak_score=float(np.max(scores)),
                mean_score=float(np.mean(scores)),
            )
        )
    regions.sort(key=lambda region: region.peak_score, reverse=True)
    regions = [
        DefectRegion(
            region_id=index,
            start_angle_degrees=region.start_angle_degrees,
            end_angle_degrees=region.end_angle_degrees,
            radial_start=region.radial_start,
            radial_end=region.radial_end,
            area=region.area,
            peak_score=region.peak_score,
            mean_score=region.mean_score,
        )
        for index, region in enumerate(regions, start=1)
    ]
    return retained, regions


def detect_ring_result(ring_result, model):
    analysis = analyze_ring_result(
        ring_result,
        minimum_periods=model.minimum_periods,
        maximum_periods=model.maximum_periods,
    )
    score_map = _standardize_features(analysis.feature_maps, model)
    candidate_mask, regions = _regions_from_map(score_map, model.threshold)
    anomaly_score = (
        float(np.quantile(score_map, 0.9995)) if score_map.size else 0.0
    )
    return analysis, score_map, candidate_mask, regions, anomaly_score


def detect_path(image_path, model):
    image_path = Path(image_path)
    try:
        ring_result = process_image_path(
            image_path,
            output_size=model.output_size,
            angle_samples=model.angle_samples,
        )
        analysis, score_map, candidate_mask, regions, anomaly_score = (
            detect_ring_result(ring_result, model)
        )
        return DetectionResult(
            image_path=image_path,
            status="ok",
            message="",
            anomaly_score=anomaly_score,
            threshold=model.threshold,
            period_count=analysis.period_count,
            phase_offset=analysis.phase_offset,
            regions=regions,
            ring_result=ring_result,
            feature_maps=analysis.feature_maps,
            anomaly_map=score_map,
            candidate_mask=candidate_mask,
        )
    except Exception as error:
        return DetectionResult(
            image_path=image_path,
            status="failed",
            message=str(error),
            anomaly_score=float("nan"),
            threshold=model.threshold,
            period_count=0,
            phase_offset=0,
            regions=[],
        )


def _write_png(path, image):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise OSError(f"无法编码图像：{path}")
    encoded.tofile(str(path))


def _colorize_score_map(score_map, threshold):
    display = np.clip(score_map / max(threshold * 1.5, 1e-6), 0.0, 1.0)
    gray = np.rint(display * 255.0).astype(np.uint8)
    return cv2.applyColorMap(gray, cv2.COLORMAP_TURBO)


def _source_candidate_mask(result):
    ring = result.ring_result
    polar_mask = result.candidate_mask
    height, width = polar_mask.shape
    ys, xs = np.where(polar_mask > 0)
    corrected_mask = np.zeros(ring.corrected.shape[:2], dtype=np.uint8)
    if len(xs):
        angles = 2.0 * np.pi * xs / width
        fraction = ys / max(height - 1, 1)
        inner = ring.inner_boundary[xs]
        outer = ring.outer_boundary[xs]
        radius = outer - fraction * (outer - inner)
        center = ring.corrected_outer_circle
        corrected_x = np.rint(center.x + radius * np.cos(angles)).astype(int)
        corrected_y = np.rint(center.y + radius * np.sin(angles)).astype(int)
        valid = (
            (corrected_x >= 0)
            & (corrected_x < corrected_mask.shape[1])
            & (corrected_y >= 0)
            & (corrected_y < corrected_mask.shape[0])
        )
        corrected_mask[corrected_y[valid], corrected_x[valid]] = 255
        corrected_mask = cv2.dilate(
            corrected_mask, np.ones((3, 3), dtype=np.uint8)
        )
    inverse = cv2.invertAffineTransform(ring.rectification_matrix)
    return cv2.warpAffine(
        corrected_mask,
        inverse,
        (ring.source.shape[1], ring.source.shape[0]),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )


def save_detection_artifacts(result, output_dir, stem):
    if result.status != "ok":
        return {}
    output_dir = Path(output_dir)
    heatmap = _colorize_score_map(result.anomaly_map, result.threshold)
    polar_overlay = result.ring_result.polar_image.copy()
    candidate = result.candidate_mask.astype(bool)
    polar_overlay[candidate] = (
        0.35 * polar_overlay[candidate] + 0.65 * np.array([0, 0, 255])
    ).astype(np.uint8)
    contours, _ = cv2.findContours(
        result.candidate_mask.astype(np.uint8),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    cv2.drawContours(polar_overlay, contours, -1, (0, 255, 255), 1)

    source_mask = _source_candidate_mask(result)
    source_overlay = result.ring_result.source.copy()
    source_pixels = source_mask > 0
    source_overlay[source_pixels] = (
        0.35 * source_overlay[source_pixels] + 0.65 * np.array([0, 0, 255])
    ).astype(np.uint8)
    source_contours, _ = cv2.findContours(
        source_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(source_overlay, source_contours, -1, (0, 255, 255), 2)

    paths = {
        "heatmap": output_dir / "heatmaps" / f"{stem}_heatmap.png",
        "polar_overlay": output_dir
        / "polar_overlays"
        / f"{stem}_polar.png",
        "source_overlay": output_dir
        / "source_overlays"
        / f"{stem}_source.png",
    }
    _write_png(paths["heatmap"], heatmap)
    _write_png(paths["polar_overlay"], polar_overlay)
    _write_png(paths["source_overlay"], source_overlay)
    return {name: str(path) for name, path in paths.items()}


def run_detection(input_path, model_path, output_dir):
    model = PolarAnomalyModel.load(model_path)
    image_paths = iter_image_paths(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    region_rows = []
    for index, image_path in enumerate(image_paths):
        result = detect_path(image_path, model)
        stem = f"{index:04d}_{image_path.stem}"
        artifacts = save_detection_artifacts(result, output_dir, stem)
        summaries.append(
            {
                "image_path": str(image_path),
                "status": result.status,
                "message": result.message,
                "anomaly_score": result.anomaly_score,
                "threshold": result.threshold,
                "period_count": result.period_count,
                "region_count": len(result.regions),
                **artifacts,
            }
        )
        for region in result.regions:
            region_rows.append(
                {
                    "image_path": str(image_path),
                    **asdict(region),
                }
            )
    _write_csv(
        output_dir / "predictions.csv",
        summaries,
        [
            "image_path",
            "status",
            "message",
            "anomaly_score",
            "threshold",
            "period_count",
            "region_count",
            "heatmap",
            "polar_overlay",
            "source_overlay",
        ],
    )
    _write_csv(
        output_dir / "regions.csv",
        region_rows,
        [
            "image_path",
            "region_id",
            "start_angle_degrees",
            "end_angle_degrees",
            "radial_start",
            "radial_end",
            "area",
            "peak_score",
            "mean_score",
        ],
    )
    successful = [row for row in summaries if row["status"] == "ok"]
    report = {
        "input_images": len(image_paths),
        "successful_images": len(successful),
        "failed_images": len(image_paths) - len(successful),
        "images_with_regions": sum(
            int(row["region_count"] > 0) for row in successful
        ),
        "threshold": model.threshold,
    }
    if successful:
        scores = np.asarray(
            [row["anomaly_score"] for row in successful], dtype=np.float64
        )
        report["score_distribution"] = {
            "minimum": float(np.min(scores)),
            "median": float(np.median(scores)),
            "maximum": float(np.max(scores)),
            "p90": float(np.quantile(scores, 0.90)),
            "p95": float(np.quantile(scores, 0.95)),
        }
        report["highest_scoring_images"] = sorted(
            (
                {
                    "image_path": row["image_path"],
                    "anomaly_score": row["anomaly_score"],
                    "region_count": row["region_count"],
                }
                for row in successful
            ),
            key=lambda row: row["anomaly_score"],
            reverse=True,
        )[:20]
    (output_dir / "detection_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _write_csv(path, rows: Iterable[dict], fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
