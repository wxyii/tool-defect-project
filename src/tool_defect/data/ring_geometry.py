"""圆形刀片的几何定位、环形区域提取和极坐标展开。"""

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile

import cv2
import numpy as np


_plot_cache = Path(tempfile.gettempdir()) / "tool_defect_matplotlib"
_plot_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_plot_cache))
os.environ.setdefault("XDG_CACHE_HOME", str(_plot_cache))

import matplotlib


matplotlib.use("Agg")
from matplotlib import font_manager
from matplotlib import pyplot as plt


def _chinese_font():
    candidates = (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            return font_manager.FontProperties(fname=candidate)
    return None


_CHINESE_FONT = _chinese_font()


@dataclass(frozen=True)
class Circle:
    """以像素为单位表示一个圆。"""

    x: float
    y: float
    radius: float


@dataclass(frozen=True)
class RingResult:
    """单张刀片图像经过完整几何处理后的结果。"""

    source: np.ndarray
    outer_circle: Circle
    inner_circle: Circle
    corrected: np.ndarray
    corrected_outer_circle: Circle
    corrected_inner_circle: Circle
    annular_roi: np.ndarray
    polar_image: np.ndarray


def read_color_image(image_path):
    """读取含中文路径的彩色图像。"""

    path = Path(image_path)
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError as error:
        raise ValueError(f"无法读取图像：{path}") from error
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图像：{path}")
    return image


def _working_image(image, max_side=512):
    height, width = image.shape[:2]
    scale = min(1.0, float(max_side) / max(height, width))
    if scale == 1.0:
        return image, scale
    resized = cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_AREA,
    )
    return resized, scale


def _outer_circle_hough(grayscale):
    size = min(grayscale.shape)
    blurred = cv2.GaussianBlur(grayscale, (7, 7), 1.5)
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(8, int(size * 0.08)),
        param1=100,
        param2=36,
        minRadius=max(4, int(size * 0.30)),
        maxRadius=max(5, int(size * 0.52)),
    )
    if circles is None:
        return None

    candidates = circles[0]
    image_center = np.array(
        [grayscale.shape[1] / 2.0, grayscale.shape[0] / 2.0]
    )
    offsets = np.linalg.norm(candidates[:, :2] - image_center, axis=1)
    central = candidates[offsets < size * 0.20]
    if len(central):
        candidates = central

    gradient_x = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gradient_x, gradient_y)
    angles = np.linspace(0.0, 2.0 * np.pi, 720, endpoint=False)

    # 真正的外轮廓会在完整圆周上持续产生强梯度；此评分可排除由
    # 图像边缘、黑色填充角或局部纹理形成的大半径伪圆。
    best = max(
        candidates,
        key=lambda circle: float(
            np.mean(
                _circle_samples(
                    gradient,
                    float(circle[0]),
                    float(circle[1]),
                    float(circle[2]),
                    angles,
                )
            )
        ),
    )
    return Circle(float(best[0]), float(best[1]), float(best[2]))


def _outer_circle_contour(grayscale):
    """霍夫检测失败时，以中心附近最大闭合轮廓作为保底。"""

    height, width = grayscale.shape
    blurred = cv2.GaussianBlur(grayscale, (7, 7), 1.5)
    edges = cv2.Canny(blurred, 40, 120)
    edges = cv2.morphologyEx(
        edges,
        cv2.MORPH_CLOSE,
        np.ones((5, 5), dtype=np.uint8),
    )
    contours, _ = cv2.findContours(
        edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    image_center = np.array([width / 2.0, height / 2.0])
    candidates = []
    for contour in contours:
        (x, y), radius = cv2.minEnclosingCircle(contour)
        offset = np.linalg.norm(np.array([x, y]) - image_center)
        if radius >= min(height, width) * 0.25 and offset < min(height, width) * 0.25:
            candidates.append((radius - 0.5 * offset, Circle(x, y, radius)))
    if not candidates:
        raise RuntimeError("未能定位刀片外圆")
    return max(candidates, key=lambda item: item[0])[1]


def _circle_samples(image, center_x, center_y, radius, angles):
    x = np.rint(center_x + radius * np.cos(angles)).astype(np.int32)
    y = np.rint(center_y + radius * np.sin(angles)).astype(np.int32)
    x = np.clip(x, 0, image.shape[1] - 1)
    y = np.clip(y, 0, image.shape[0] - 1)
    return image[y, x]


def _inner_circle_from_radial_gradient(grayscale, outer):
    blurred = cv2.GaussianBlur(grayscale, (5, 5), 1.0)
    gradient_x = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gradient_x, gradient_y)

    angles = np.linspace(0.0, 2.0 * np.pi, 720, endpoint=False)
    radii = np.arange(
        max(3, int(round(outer.radius * 0.38))),
        max(4, int(round(outer.radius * 0.69))),
        dtype=np.int32,
    )
    if len(radii) < 3:
        raise RuntimeError("外圆尺寸过小，无法定位内圆")

    profile = np.array(
        [
            np.mean(
                _circle_samples(
                    gradient, outer.x, outer.y, float(radius), angles
                )
            )
            for radius in radii
        ],
        dtype=np.float32,
    )
    profile = cv2.GaussianBlur(profile.reshape(-1, 1), (1, 9), 0).ravel()

    local_peaks = [
        index
        for index in range(1, len(profile) - 1)
        if profile[index] >= profile[index - 1]
        and profile[index] >= profile[index + 1]
    ]
    threshold = float(profile.max()) * 0.30
    significant = [index for index in local_peaks if profile[index] >= threshold]
    peak_index = significant[0] if significant else int(np.argmax(profile))
    radius = float(radii[peak_index])

    # 只在很小邻域内修正内圆圆心，并对偏离外圆圆心施加惩罚。
    search_extent = max(1, int(round(outer.radius * 0.025)))
    offsets = np.linspace(-search_extent, search_extent, 7)
    base_score = max(float(profile[peak_index]), 1.0)
    best = (float("-inf"), outer.x, outer.y)
    for offset_y in offsets:
        for offset_x in offsets:
            values = _circle_samples(
                gradient,
                outer.x + float(offset_x),
                outer.y + float(offset_y),
                radius,
                angles,
            )
            displacement = np.hypot(offset_x, offset_y)
            score = float(np.mean(values)) - base_score * 0.08 * displacement
            if score > best[0]:
                best = (
                    score,
                    outer.x + float(offset_x),
                    outer.y + float(offset_y),
                )
    return Circle(best[1], best[2], radius)


def locate_circles(image):
    """定位刀片的外圆和内圆。"""

    working, scale = _working_image(image)
    grayscale = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
    outer = _outer_circle_hough(grayscale)
    if outer is None:
        outer = _outer_circle_contour(grayscale)
    inner = _inner_circle_from_radial_gradient(grayscale, outer)

    inverse_scale = 1.0 / scale
    return (
        Circle(
            outer.x * inverse_scale,
            outer.y * inverse_scale,
            outer.radius * inverse_scale*1.1,
        ),
        Circle(
            inner.x * inverse_scale,
            inner.y * inverse_scale,
            inner.radius * inverse_scale*1.5,
        ),
    )


def correct_center_and_scale(
    image,
    outer_circle,
    inner_circle,
    output_size=512,
    outer_margin=0.04,
):
    """把外圆圆心移到画面中心，并把外圆统一缩放到固定半径。"""

    target_center = output_size / 2.0
    target_outer_radius = output_size * (0.5 - outer_margin)
    scale = target_outer_radius / outer_circle.radius
    matrix = np.array(
        [
            [scale, 0.0, target_center - scale * outer_circle.x],
            [0.0, scale, target_center - scale * outer_circle.y],
        ],
        dtype=np.float32,
    )
    corrected = cv2.warpAffine(
        image,
        matrix,
        (output_size, output_size),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    corrected_outer = Circle(
        target_center, target_center, target_outer_radius
    )
    corrected_inner = Circle(
        target_center + scale * (inner_circle.x - outer_circle.x),
        target_center + scale * (inner_circle.y - outer_circle.y),
        scale * inner_circle.radius,
    )
    return corrected, corrected_outer, corrected_inner


def extract_annular_roi(image, inner_circle, outer_circle):
    """保留内外圆之间的环形区域，其余像素置零。"""

    height, width = image.shape[:2]
    y, x = np.ogrid[:height, :width]
    center_x = (inner_circle.x + outer_circle.x) / 2.0
    center_y = (inner_circle.y + outer_circle.y) / 2.0
    distance_squared = (x - center_x) ** 2 + (y - center_y) ** 2
    mask = (
        (distance_squared >= inner_circle.radius**2)
        & (distance_squared <= outer_circle.radius**2)
    )
    result = np.zeros_like(image)
    result[mask] = image[mask]
    return result


def unwrap_annulus(image, inner_circle, outer_circle, angle_samples=1440):
    """把环形区域展开为“半径 × 角度”的矩形图。"""

    center = (
        (inner_circle.x + outer_circle.x) / 2.0,
        (inner_circle.y + outer_circle.y) / 2.0,
    )
    maximum_radius = int(np.ceil(outer_circle.radius)) + 1
    polar = cv2.warpPolar(
        image,
        (maximum_radius, angle_samples),
        center,
        float(outer_circle.radius),
        cv2.WARP_POLAR_LINEAR | cv2.WARP_FILL_OUTLIERS,
    )
    inner_column = int(np.clip(round(inner_circle.radius), 0, maximum_radius - 1))
    outer_column = int(
        np.clip(round(outer_circle.radius), inner_column + 1, maximum_radius)
    )
    annulus = polar[:, inner_column:outer_column]
    # 横轴为角度，纵轴从外圆到内圆，便于横向观察整圈缺陷。
    return np.flipud(np.transpose(annulus, (1, 0, 2)))


def process_ring_image(image, output_size=512, angle_samples=1440):
    """执行圆定位、几何校正、环形提取和极坐标展开。"""

    outer, inner = locate_circles(image)
    corrected, corrected_outer, corrected_inner = correct_center_and_scale(
        image,
        outer,
        inner,
        output_size=output_size,
    )
    annular_roi = extract_annular_roi(
        corrected, corrected_inner, corrected_outer
    )
    polar_image = unwrap_annulus(
        corrected,
        corrected_inner,
        corrected_outer,
        angle_samples=angle_samples,
    )
    return RingResult(
        source=image,
        outer_circle=outer,
        inner_circle=inner,
        corrected=corrected,
        corrected_outer_circle=corrected_outer,
        corrected_inner_circle=corrected_inner,
        annular_roi=annular_roi,
        polar_image=polar_image,
    )


def _circle_overlay(result):
    overlay = result.source.copy()
    line_width = max(2, int(round(min(overlay.shape[:2]) / 300)))
    outer = result.outer_circle
    inner = result.inner_circle
    cv2.circle(
        overlay,
        (int(round(outer.x)), int(round(outer.y))),
        int(round(outer.radius)),
        (0, 220, 0),
        line_width,
        cv2.LINE_AA,
    )
    cv2.circle(
        overlay,
        (int(round(inner.x)), int(round(inner.y))),
        int(round(inner.radius)),
        (0, 0, 255),
        line_width,
        cv2.LINE_AA,
    )
    cv2.drawMarker(
        overlay,
        (int(round(outer.x)), int(round(outer.y))),
        (255, 0, 255),
        cv2.MARKER_CROSS,
        max(12, line_width * 5),
        line_width,
    )
    return overlay


def _rgb(image):
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def save_pipeline_figure(result, output_path, title=None):
    """保存单张图像的五阶段流程图。"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    images = [
        result.source,
        _circle_overlay(result),
        result.corrected,
        result.annular_roi,
        result.polar_image,
    ]
    labels = ["原始图像", "内外圆定位", "中心和尺度校正", "环形区域", "极坐标展开"]
    figure = plt.figure(figsize=(18, 8), constrained_layout=True)
    grid = figure.add_gridspec(2, 4)
    axes = [
        figure.add_subplot(grid[0, 0]),
        figure.add_subplot(grid[0, 1]),
        figure.add_subplot(grid[0, 2]),
        figure.add_subplot(grid[0, 3]),
        figure.add_subplot(grid[1, :]),
    ]
    for axis, image, label in zip(axes, images, labels):
        axis.imshow(_rgb(image))
        axis.set_title(label, fontproperties=_CHINESE_FONT)
        axis.axis("off")
    if title:
        figure.suptitle(title, fontsize=16, fontproperties=_CHINESE_FONT)
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def save_comparison_figure(results, labels, output_path):
    """保存多类刀片在统一尺度下的定位和展开对比图。"""

    if len(results) != len(labels):
        raise ValueError("结果数量与标签数量不一致")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(
        len(results),
        4,
        figsize=(18, 4.5 * len(results)),
        squeeze=False,
        constrained_layout=True,
    )
    column_labels = ["圆定位", "几何校正", "环形区域", "极坐标展开"]
    for row, (result, label) in enumerate(zip(results, labels)):
        images = [
            _circle_overlay(result),
            result.corrected,
            result.annular_roi,
            result.polar_image,
        ]
        for column, image in enumerate(images):
            axes[row, column].imshow(_rgb(image), aspect="auto" if column == 3 else None)
            axes[row, column].axis("off")
            if row == 0:
                axes[row, column].set_title(
                    column_labels[column], fontproperties=_CHINESE_FONT
                )
            if column == 0:
                axes[row, column].text(
                    -0.035,
                    0.5,
                    label,
                    transform=axes[row, column].transAxes,
                    rotation=90,
                    va="center",
                    ha="right",
                    fontsize=14,
                    fontproperties=_CHINESE_FONT,
                )
    figure.savefig(output_path, dpi=150)
    plt.close(figure)


def process_image_path(image_path, output_size=512, angle_samples=1440):
    """读取路径并执行完整处理。"""

    return process_ring_image(
        read_color_image(image_path),
        output_size=output_size,
        angle_samples=angle_samples,
    )
