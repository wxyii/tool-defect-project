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
class Ellipse:
    """以像素为单位表示一个椭圆，角度对应长轴方向。"""

    x: float
    y: float
    major_radius: float
    minor_radius: float
    angle: float


@dataclass(frozen=True)
class RingResult:
    """单张刀片图像经过完整几何处理后的结果。"""

    source: np.ndarray
    outer_ellipse: Ellipse
    inner_ellipse: Ellipse
    outer_circle: Circle
    inner_circle: Circle
    corrected: np.ndarray
    rectification_matrix: np.ndarray
    corrected_outer_circle: Circle
    corrected_inner_circle: Circle
    annular_roi: np.ndarray
    polar_image: np.ndarray
    raw_inner_boundary: np.ndarray
    raw_outer_boundary: np.ndarray
    inner_boundary: np.ndarray
    outer_boundary: np.ndarray


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


def _canonical_ellipse(fitted):
    """把 OpenCV 椭圆统一为长轴半径、短轴半径和长轴角度。"""

    (x, y), (width, height), angle = fitted
    if width >= height:
        major_radius = width / 2.0
        minor_radius = height / 2.0
        major_angle = angle
    else:
        major_radius = height / 2.0
        minor_radius = width / 2.0
        major_angle = angle - 90.0
    return Ellipse(
        float(x),
        float(y),
        float(major_radius),
        float(minor_radius),
        float(major_angle % 180.0),
    )


def _ellipse_samples(image, ellipse, angles):
    angle = np.deg2rad(ellipse.angle)
    cosine = np.cos(angle)
    sine = np.sin(angle)
    major = ellipse.major_radius * np.cos(angles)
    minor = ellipse.minor_radius * np.sin(angles)
    x = np.rint(ellipse.x + major * cosine - minor * sine).astype(np.int32)
    y = np.rint(ellipse.y + major * sine + minor * cosine).astype(np.int32)
    valid = (
        (x >= 0)
        & (x < image.shape[1])
        & (y >= 0)
        & (y < image.shape[0])
    )
    return image[y[valid], x[valid]], float(np.mean(valid))


def _fit_outer_ellipse(grayscale):
    """从边缘轮廓中选择完整圆周支持最强的外椭圆。"""

    height, width = grayscale.shape
    size = min(height, width)
    blurred = cv2.GaussianBlur(grayscale, (5, 5), 1.0)
    edges = cv2.Canny(blurred, 35, 110)
    contours, _ = cv2.findContours(
        edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE
    )
    gradient_x = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gradient_x, gradient_y)
    image_center = np.array([width / 2.0, height / 2.0])
    angles = np.linspace(0.0, 2.0 * np.pi, 720, endpoint=False)
    candidates = []
    try:
        rough_outer = _outer_circle_contour(grayscale)
    except RuntimeError:
        rough_outer = _outer_circle_hough(grayscale)

    for contour in contours:
        if len(contour) < 30:
            continue
        try:
            ellipse = _canonical_ellipse(cv2.fitEllipse(contour))
        except cv2.error:
            continue
        center_offset = float(
            np.linalg.norm(
                np.array([ellipse.x, ellipse.y], dtype=np.float32)
                - image_center
            )
        )
        aspect_ratio = ellipse.minor_radius / ellipse.major_radius
        if rough_outer is not None:
            rough_ratio = ellipse.major_radius / rough_outer.radius
            rough_center_offset = np.hypot(
                ellipse.x - rough_outer.x,
                ellipse.y - rough_outer.y,
            )
            if not (
                0.96 <= rough_ratio <= 1.02
                and rough_center_offset <= rough_outer.radius * 0.10
            ):
                continue
        if not (
            size * 0.28 <= ellipse.major_radius <= size * 0.58
            and size * 0.18 <= ellipse.minor_radius <= ellipse.major_radius
            and aspect_ratio >= 0.45
            and center_offset <= size * 0.28
        ):
            continue

        values, valid_fraction = _ellipse_samples(gradient, ellipse, angles)
        if valid_fraction < 0.80 or not len(values):
            continue
        perimeter = np.pi * (
            3.0 * (ellipse.major_radius + ellipse.minor_radius)
            - np.sqrt(
                (3.0 * ellipse.major_radius + ellipse.minor_radius)
                * (ellipse.major_radius + 3.0 * ellipse.minor_radius)
            )
        )
        coverage = min(
            1.0,
            float(cv2.arcLength(contour, False)) / max(perimeter, 1.0),
        )
        geometric_radius = np.sqrt(
            ellipse.major_radius * ellipse.minor_radius
        )
        score = (
            float(np.mean(values)) * (0.4 + 0.6 * coverage)
            + 80.0 * geometric_radius / size
            - 40.0 * center_offset / size
        )
        candidates.append((score, ellipse))

    if candidates:
        return max(candidates, key=lambda item: item[0])[1]

    # 边缘轮廓断裂时，退回已有圆定位，并将其视为零倾斜椭圆。
    circle = rough_outer
    if circle is None:
        circle = _outer_circle_hough(grayscale)
    if circle is None:
        circle = _outer_circle_contour(grayscale)
    return Ellipse(
        circle.x,
        circle.y,
        circle.radius,
        circle.radius,
        0.0,
    )


def locate_outer_ellipse(image):
    """定位斜拍刀片的外椭圆。"""

    working, scale = _working_image(image)
    grayscale = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
    ellipse = _fit_outer_ellipse(grayscale)
    inverse_scale = 1.0 / scale
    return Ellipse(
        ellipse.x * inverse_scale,
        ellipse.y * inverse_scale,
        ellipse.major_radius * inverse_scale,
        ellipse.minor_radius * inverse_scale,
        ellipse.angle,
    )


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


def locate_circles(
    image,
    outer_radius_scale=1.1,
    inner_radius_scale=1.5,
):
    """兼容旧流程的圆定位接口。

    半径缩放参数保留此前的人工调节行为；新的斜拍校正主流程不依赖
    这两个经验缩放值。
    """

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
            outer.radius * inverse_scale * outer_radius_scale,
        ),
        Circle(
            inner.x * inverse_scale,
            inner.y * inverse_scale,
            inner.radius * inverse_scale * inner_radius_scale,
        ),
    )


def rectify_ellipse(
    image,
    outer_ellipse,
    output_size=512,
    outer_margin=0.04,
):
    """通过旋转和非等比缩放把外椭圆恢复为正圆。"""

    target_center = output_size / 2.0
    target_radius = output_size * (0.5 - outer_margin)
    angle = np.deg2rad(outer_ellipse.angle)
    cosine = np.cos(angle)
    sine = np.sin(angle)
    rotate_to_axes = np.array(
        [[cosine, sine], [-sine, cosine]],
        dtype=np.float64,
    )
    axis_scale = np.diag(
        [
            target_radius / outer_ellipse.major_radius,
            target_radius / outer_ellipse.minor_radius,
        ]
    )
    linear = axis_scale @ rotate_to_axes
    center = np.array([outer_ellipse.x, outer_ellipse.y], dtype=np.float64)
    translation = (
        np.array([target_center, target_center], dtype=np.float64)
        - linear @ center
    )
    matrix = np.column_stack([linear, translation]).astype(np.float32)
    corrected = cv2.warpAffine(
        image,
        matrix,
        (output_size, output_size),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    return (
        corrected,
        Circle(target_center, target_center, target_radius),
        matrix,
    )


def _inverse_circle_as_ellipse(circle, outer_ellipse, corrected_outer):
    """把校正图中的内圆映射回原图，供定位结果叠加显示。"""

    ratio = circle.radius / corrected_outer.radius
    angle = np.deg2rad(outer_ellipse.angle)
    cosine = np.cos(angle)
    sine = np.sin(angle)
    offset = np.array(
        [
            (circle.x - corrected_outer.x)
            * outer_ellipse.major_radius
            / corrected_outer.radius,
            (circle.y - corrected_outer.y)
            * outer_ellipse.minor_radius
            / corrected_outer.radius,
        ]
    )
    rotated_offset = np.array(
        [
            cosine * offset[0] - sine * offset[1],
            sine * offset[0] + cosine * offset[1],
        ]
    )
    return Ellipse(
        outer_ellipse.x + float(rotated_offset[0]),
        outer_ellipse.y + float(rotated_offset[1]),
        outer_ellipse.major_radius * ratio,
        outer_ellipse.minor_radius * ratio,
        outer_ellipse.angle,
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


def _circular_smooth(values, window):
    window = max(3, int(window) | 1)
    half = window // 2
    padded = np.pad(values, (half, half), mode="wrap")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window)
    median = np.median(windows, axis=-1).astype(np.float32)
    gaussian_input = np.pad(median, (half, half), mode="wrap")
    smoothed = cv2.GaussianBlur(
        gaussian_input.reshape(1, -1),
        (window, 1),
        0,
    ).ravel()
    return smoothed[half:-half]


def _fit_low_frequency_boundary(
    values,
    expected_radius,
    maximum_deviation,
    harmonics=4,
):
    """稳健拟合低频周期边界，避免把齿纹或局部缺口当作整体形变。"""

    count = len(values)
    angles = np.linspace(0.0, 2.0 * np.pi, count, endpoint=False)
    columns = [np.ones(count, dtype=np.float64)]
    for order in range(1, harmonics + 1):
        columns.extend(
            [
                np.cos(order * angles),
                np.sin(order * angles),
            ]
        )
    design = np.column_stack(columns)
    observations = np.clip(
        np.asarray(values, dtype=np.float64),
        expected_radius - maximum_deviation,
        expected_radius + maximum_deviation,
    )
    weights = np.ones(count, dtype=np.float64)
    coefficients = np.zeros(design.shape[1], dtype=np.float64)
    for _ in range(4):
        weighted_design = design * weights[:, None]
        coefficients, _, _, _ = np.linalg.lstsq(
            weighted_design,
            observations * weights,
            rcond=None,
        )
        residual = observations - design @ coefficients
        median = np.median(residual)
        scale = max(
            1.4826 * np.median(np.abs(residual - median)),
            0.5,
        )
        normalized = np.abs(residual - median) / (2.5 * scale)
        weights = 1.0 / np.maximum(1.0, normalized)
    fitted = design @ coefficients
    return np.clip(
        fitted,
        expected_radius - maximum_deviation,
        expected_radius + maximum_deviation,
    ).astype(np.float32)


def _track_single_boundary(
    gradient,
    center,
    expected_radius,
    minimum_radius,
    maximum_radius,
    angles,
):
    radii = np.arange(
        int(np.floor(minimum_radius)),
        int(np.ceil(maximum_radius)) + 1,
        dtype=np.float32,
    )
    cosine = np.cos(angles)
    sine = np.sin(angles)
    map_x = center[0] + radii[:, None] * cosine[None, :]
    map_y = center[1] + radii[:, None] * sine[None, :]
    samples = cv2.remap(
        gradient,
        map_x.astype(np.float32),
        map_y.astype(np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    radial_half_width = max(
        expected_radius - minimum_radius,
        maximum_radius - expected_radius,
        1.0,
    )
    distance_penalty = (
        np.abs(radii - expected_radius) / radial_half_width
    )[:, None]
    gradient_scale = max(float(np.percentile(samples, 95)), 1.0)
    scores = samples - gradient_scale * 0.50 * distance_penalty
    return radii[np.argmax(scores, axis=0)]


def track_annular_boundaries(
    image,
    inner_circle,
    outer_circle,
    angle_samples=1440,
):
    """逐角度跟踪内外边界，同时返回原始曲线和平滑曲线。"""

    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(grayscale, (5, 5), 1.0)
    gradient_x = cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(blurred, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gradient_x, gradient_y)
    angles = np.linspace(0.0, 2.0 * np.pi, angle_samples, endpoint=False)
    center = (outer_circle.x, outer_circle.y)
    raw_inner = _track_single_boundary(
        gradient,
        center,
        inner_circle.radius,
        max(2.0, inner_circle.radius - outer_circle.radius * 0.06),
        inner_circle.radius + outer_circle.radius * 0.06,
        angles,
    )
    raw_outer = _track_single_boundary(
        gradient,
        center,
        outer_circle.radius,
        outer_circle.radius * 0.94,
        outer_circle.radius * 1.025,
        angles,
    )
    smoothing_window = max(7, round(angle_samples / 120))
    filtered_inner = _circular_smooth(raw_inner, smoothing_window)
    filtered_outer = _circular_smooth(raw_outer, smoothing_window)
    inner = _fit_low_frequency_boundary(
        filtered_inner,
        inner_circle.radius,
        outer_circle.radius * 0.06,
    )
    outer = _fit_low_frequency_boundary(
        filtered_outer,
        outer_circle.radius,
        outer_circle.radius * 0.035,
    )
    minimum_width = max(3.0, outer_circle.radius * 0.10)
    outer = np.maximum(outer, inner + minimum_width)
    return raw_inner, raw_outer, inner, outer


def extract_adaptive_annular_roi(
    image,
    center,
    inner_boundary,
    outer_boundary,
):
    """按照逐角度边界曲线提取环形区域。"""

    height, width = image.shape[:2]
    y, x = np.ogrid[:height, :width]
    delta_x = x - center[0]
    delta_y = y - center[1]
    radius = np.sqrt(delta_x**2 + delta_y**2)
    angle = np.mod(np.arctan2(delta_y, delta_x), 2.0 * np.pi)
    indices = np.mod(
        np.rint(angle * len(inner_boundary) / (2.0 * np.pi)).astype(np.int32),
        len(inner_boundary),
    )
    mask = (
        (radius >= inner_boundary[indices])
        & (radius <= outer_boundary[indices])
    )
    result = np.zeros_like(image)
    result[mask] = image[mask]
    return result


def unwrap_annulus_normalized(
    image,
    center,
    inner_boundary,
    outer_boundary,
    radial_samples=None,
):
    """按每个角度的内外边界做归一化径向重采样。"""

    angle_samples = len(inner_boundary)
    if radial_samples is None:
        radial_samples = max(
            2,
            int(round(float(np.median(outer_boundary - inner_boundary)))),
        )
    angles = np.linspace(0.0, 2.0 * np.pi, angle_samples, endpoint=False)
    # 第一行对应外圆，最后一行对应内圆。
    normalized_radius = np.linspace(
        1.0, 0.0, radial_samples, dtype=np.float32
    )[:, None]
    radii = (
        inner_boundary[None, :]
        + normalized_radius
        * (outer_boundary - inner_boundary)[None, :]
    )
    map_x = center[0] + radii * np.cos(angles)[None, :]
    map_y = center[1] + radii * np.sin(angles)[None, :]
    return cv2.remap(
        image,
        map_x.astype(np.float32),
        map_y.astype(np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )


def process_ring_image(image, output_size=512, angle_samples=1440):
    """执行椭圆定位、斜拍校正、边界跟踪和归一化展开。"""

    outer_ellipse = locate_outer_ellipse(image)
    corrected, corrected_outer, rectification_matrix = rectify_ellipse(
        image,
        outer_ellipse,
        output_size=output_size,
    )
    grayscale = cv2.cvtColor(corrected, cv2.COLOR_BGR2GRAY)
    detected_inner = _inner_circle_from_radial_gradient(
        grayscale, corrected_outer
    )
    # 同心圆是平面环形刀片的几何约束，避免局部反光把展开中心拉偏。
    corrected_inner = Circle(
        corrected_outer.x,
        corrected_outer.y,
        detected_inner.radius,
    )
    inner_ellipse = _inverse_circle_as_ellipse(
        corrected_inner,
        outer_ellipse,
        corrected_outer,
    )
    raw_inner, raw_outer, inner_boundary, outer_boundary = (
        track_annular_boundaries(
            corrected,
            corrected_inner,
            corrected_outer,
            angle_samples=angle_samples,
        )
    )
    center = (corrected_outer.x, corrected_outer.y)
    annular_roi = extract_adaptive_annular_roi(
        corrected,
        center,
        inner_boundary,
        outer_boundary,
    )
    polar_image = unwrap_annulus_normalized(
        corrected,
        center,
        inner_boundary,
        outer_boundary,
    )
    return RingResult(
        source=image,
        outer_ellipse=outer_ellipse,
        inner_ellipse=inner_ellipse,
        outer_circle=Circle(
            outer_ellipse.x,
            outer_ellipse.y,
            np.sqrt(
                outer_ellipse.major_radius * outer_ellipse.minor_radius
            )*2,
        ),
        inner_circle=Circle(
            inner_ellipse.x,
            inner_ellipse.y,
            np.sqrt(
                inner_ellipse.major_radius * inner_ellipse.minor_radius
            ),
        ),
        corrected=corrected,
        rectification_matrix=rectification_matrix,
        corrected_outer_circle=corrected_outer,
        corrected_inner_circle=corrected_inner,
        annular_roi=annular_roi,
        polar_image=polar_image,
        raw_inner_boundary=raw_inner,
        raw_outer_boundary=raw_outer,
        inner_boundary=inner_boundary,
        outer_boundary=outer_boundary,
    )


def _circle_overlay(result):
    overlay = result.source.copy()
    line_width = max(2, int(round(min(overlay.shape[:2]) / 300)))
    outer = result.outer_ellipse
    inner = result.inner_ellipse
    cv2.ellipse(
        overlay,
        (int(round(outer.x)), int(round(outer.y))),
        (
            int(round(outer.major_radius)),
            int(round(outer.minor_radius)),
        ),
        outer.angle,
        0,
        360,
        (0, 220, 0),
        line_width,
        cv2.LINE_AA,
    )
    cv2.ellipse(
        overlay,
        (int(round(inner.x)), int(round(inner.y))),
        (
            int(round(inner.major_radius)),
            int(round(inner.minor_radius)),
        ),
        inner.angle,
        0,
        360,
        (0, 0, 255),
        line_width,
        cv2.LINE_AA,
    )
    cv2.drawMarker(
        overlay,
        (int(round(result.outer_ellipse.x)), int(round(result.outer_ellipse.y))),
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
    labels = [
        "原始图像",
        "内外椭圆定位",
        "斜拍和尺度校正",
        "自适应环形区域",
        "边界归一化展开",
    ]
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
    column_labels = [
        "椭圆定位",
        "斜拍校正",
        "自适应环形区域",
        "边界归一化展开",
    ]
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


def save_boundary_profiles(result, output_path):
    """保存原始和平滑后的内外边界，供边缘缺陷分析使用。"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    angles = np.linspace(
        0.0,
        360.0,
        len(result.inner_boundary),
        endpoint=False,
    )
    rows = np.column_stack(
        [
            angles,
            result.raw_inner_boundary,
            result.inner_boundary,
            result.raw_outer_boundary,
            result.outer_boundary,
            result.raw_outer_boundary - result.outer_boundary,
        ]
    )
    np.savetxt(
        output_path,
        rows,
        delimiter=",",
        header=(
            "angle_degrees,raw_inner_radius,smoothed_inner_radius,"
            "raw_outer_radius,smoothed_outer_radius,outer_edge_residual"
        ),
        comments="",
        fmt="%.6f",
    )


def process_image_path(image_path, output_size=512, angle_samples=1440):
    """读取路径并执行完整处理。"""

    return process_ring_image(
        read_color_image(image_path),
        output_size=output_size,
        angle_samples=angle_samples,
    )
