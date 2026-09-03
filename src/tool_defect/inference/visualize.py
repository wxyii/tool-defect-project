"""Truthful, readable visualization of predicted tool defects."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\msyhbd.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
)


@dataclass(frozen=True)
class DefectComponent:
    """One retained connected component in model-mask coordinates."""

    area: int
    x: int
    y: int
    width: int
    height: int
    center_x: float
    center_y: float


@dataclass(frozen=True)
class VisualizationStatus:
    """Validated display text and color for one prediction."""

    text: str
    color_bgr: tuple
    component_count: int


def _read_color_image(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"input image does not exist: {path}")
    encoded = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"unable to read image: {path}")
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
        raise OSError(f"unable to encode visualization: {path}")
    encoded.tofile(str(path))


def _resolve_font_path(font_path=None):
    if font_path is not None:
        resolved = Path(font_path)
        if resolved.is_file():
            return resolved
        raise FileNotFoundError(f"中文字体不存在: {resolved}")
    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return candidate
    checked = ", ".join(str(path) for path in FONT_CANDIDATES)
    raise FileNotFoundError(f"未找到可用中文字体，已检查: {checked}")


def _validate_prediction(predicted_class, confidence):
    if predicted_class not in {"qualified", "unqualified"}:
        raise ValueError(
            "predicted_class must be 'qualified' or 'unqualified'"
        )
    confidence = float(confidence)
    if not np.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be a finite value from 0 to 1")
    return confidence


def filter_display_components(defect_mask, min_component_area=12):
    """Return a filtered display copy and retained components.

    Filtering is performed in the model mask coordinate system. The input
    array is never modified, and callers must continue saving the original
    mask as the auditable model output.
    """

    mask = np.asarray(defect_mask)
    if mask.ndim != 2:
        raise ValueError("defect_mask must be a two-dimensional array")
    if int(min_component_area) < 1:
        raise ValueError("min_component_area must be at least 1")

    binary = (mask > 0).astype(np.uint8)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary,
        connectivity=8,
    )
    filtered = np.zeros(mask.shape, dtype=np.uint8)
    components = []
    retained_labels = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < int(min_component_area):
            continue
        retained_labels.append(label)
        components.append(
            DefectComponent(
                area=area,
                x=int(stats[label, cv2.CC_STAT_LEFT]),
                y=int(stats[label, cv2.CC_STAT_TOP]),
                width=int(stats[label, cv2.CC_STAT_WIDTH]),
                height=int(stats[label, cv2.CC_STAT_HEIGHT]),
                center_x=float(centroids[label, 0]),
                center_y=float(centroids[label, 1]),
            )
        )
    if retained_labels:
        retained_lookup = np.zeros(count, dtype=np.uint8)
        retained_lookup[retained_labels] = 255
        filtered = retained_lookup[labels]
    components.sort(key=lambda component: component.area, reverse=True)
    return filtered, components


def restore_normalized_mask_to_circle(
    defect_mask,
    inner_boundary,
    outer_boundary,
    output_shape,
    center=None,
):
    """将边界归一化掩码反向映射到校正后的圆形坐标。"""

    mask = np.asarray(defect_mask)
    if mask.ndim != 2:
        raise ValueError("defect_mask 必须是二维数组")
    inner = np.asarray(inner_boundary, dtype=np.float32).reshape(-1)
    outer = np.asarray(outer_boundary, dtype=np.float32).reshape(-1)
    if inner.size < 2 or inner.size != outer.size:
        raise ValueError("内外边界必须是长度相同且至少包含两个采样点的一维数组")
    output_height, output_width = (int(value) for value in output_shape)
    if output_height < 1 or output_width < 1:
        raise ValueError("output_shape 必须包含正整数的高和宽")
    if center is None:
        center = (output_width / 2.0, output_height / 2.0)
    if len(center) != 2:
        raise ValueError("center 必须包含横坐标和纵坐标")
    center_x, center_y = (float(value) for value in center)

    y, x = np.indices((output_height, output_width), dtype=np.float32)
    radius = np.hypot(x - center_x, y - center_y)
    angle_fraction = np.mod(
        np.arctan2(y - center_y, x - center_x),
        2.0 * np.pi,
    ) / (2.0 * np.pi)
    boundary_position = angle_fraction * inner.size
    left = np.floor(boundary_position).astype(np.intp) % inner.size
    right = (left + 1) % inner.size
    fraction = boundary_position - np.floor(boundary_position)
    local_inner = inner[left] * (1.0 - fraction) + inner[right] * fraction
    local_outer = outer[left] * (1.0 - fraction) + outer[right] * fraction
    thickness = local_outer - local_inner
    valid = (
        (thickness > 0.0)
        & (radius >= local_inner)
        & (radius <= local_outer)
    )
    normalized_radius = np.divide(
        radius - local_inner,
        thickness,
        out=np.zeros_like(radius),
        where=thickness > 0.0,
    )
    normalized_radius = np.clip(normalized_radius, 0.0, 1.0)
    map_x = (angle_fraction * mask.shape[1]).astype(np.float32)
    map_y = (
        (1.0 - normalized_radius) * max(0, mask.shape[0] - 1)
    ).astype(np.float32)
    sampled = cv2.remap(
        (mask > 0).astype(np.uint8) * 255,
        map_x,
        map_y,
        cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return np.where(valid, sampled, 0).astype(np.uint8)


def build_visualization_status(
    predicted_class,
    confidence,
    raw_has_defect,
    component_count,
):
    """Build deterministic, scientifically cautious Chinese result text."""

    confidence = _validate_prediction(predicted_class, confidence)
    component_count = int(component_count)
    if component_count < 0:
        raise ValueError("component_count must not be negative")
    raw_has_defect = bool(raw_has_defect)
    confidence_text = f"分类置信度：{confidence * 100:.2f}%"

    if predicted_class == "unqualified":
        headline = f"检测结果：不合格　{confidence_text}"
        color_bgr = (20, 20, 245)
        if component_count:
            detail = f"检测到 {component_count} 处疑似缺陷"
        elif raw_has_defect:
            detail = "仅检测到低可信度微小区域，请人工复核"
        else:
            detail = "未能定位缺陷区域，请人工复核"
    else:
        headline = f"检测结果：合格　{confidence_text}"
        color_bgr = (30, 190, 30)
        if component_count:
            detail = "分类与定位结果不一致，请人工复核"
        elif raw_has_defect:
            detail = "仅检测到低可信度微小区域，请人工复核"
        else:
            detail = "未检测到缺陷区域"

    return VisualizationStatus(
        text=f"{headline}\n{detail}",
        color_bgr=color_bgr,
        component_count=component_count,
    )


def _fit_font(font_path, text, preferred_size, max_width, minimum_size=12):
    size = max(int(preferred_size), int(minimum_size))
    while size > minimum_size:
        font = ImageFont.truetype(str(font_path), size=size)
        left, _, right, _ = font.getbbox(text)
        if right - left <= max_width:
            return font
        size -= 1
    return ImageFont.truetype(str(font_path), size=minimum_size)


def _resize_body(original, max_dimension, top_height, bottom_height):
    height, width = original.shape[:2]
    available_height = int(max_dimension) - top_height - bottom_height
    if available_height < 1:
        raise ValueError("max_dimension is too small for the information bars")
    scale = min(
        1.0,
        float(max_dimension) / width,
        float(available_height) / height,
    )
    if scale >= 1.0:
        return original.copy()
    target = (
        max(1, int(round(width * scale))),
        max(1, int(round(height * scale))),
    )
    return cv2.resize(original, target, interpolation=cv2.INTER_AREA)


def _mark_components(
    image,
    display_mask,
    components,
    source_shape,
    overlay_alpha,
):
    """仅用不遮挡缺陷的空心红圈标记缺陷组件。"""

    height, width = image.shape[:2]
    resized_mask = cv2.resize(
        display_mask,
        (width, height),
        interpolation=cv2.INTER_NEAREST,
    )
    # 保留参数以兼容已有调用；生产现场标注不再绘制实心覆盖层。
    del resized_mask, overlay_alpha
    marked = image.copy()
    line_width = max(2, int(round(max(width, height) / 600)))

    source_height, source_width = source_shape
    x_scale = width / float(source_width)
    y_scale = height / float(source_height)
    minimum_radius = max(10, int(round(max(width, height) / 80)))

    for component in components:
        center = (
            int(round(component.center_x * x_scale)),
            int(round(component.center_y * y_scale)),
        )
        component_width = max(1, int(round(component.width * x_scale)))
        component_height = max(1, int(round(component.height * y_scale)))
        callout_radius = max(
            minimum_radius,
            int(round(0.65 * max(component_width, component_height))),
        )
        cv2.circle(marked, center, callout_radius, (0, 0, 255), line_width)
    return marked


def _draw_chinese_bars(body, status, font_path, top_height, bottom_height):
    height, width = body.shape[:2]
    canvas = np.full(
        (top_height + height + bottom_height, width, 3),
        24,
        dtype=np.uint8,
    )
    canvas[top_height : top_height + height] = body

    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil_image)
    padding = max(8, int(round(width * 0.015)))
    headline, detail = status.text.split("\n", maxsplit=1)
    preferred_headline = max(18, int(round(width * 0.028)))
    preferred_detail = max(15, int(round(preferred_headline * 0.72)))
    headline_font = _fit_font(
        font_path,
        headline,
        preferred_headline,
        max(1, width - 2 * padding),
    )
    detail_font = _fit_font(
        font_path,
        detail,
        preferred_detail,
        max(1, width - 2 * padding),
    )
    status_rgb = tuple(reversed(status.color_bgr))

    line_width = max(4, int(round(width / 300)))
    draw.rectangle((0, 0, line_width, top_height), fill=status_rgb)
    draw.text(
        (padding + line_width, padding),
        headline,
        font=headline_font,
        fill=status_rgb,
    )
    headline_box = draw.textbbox((0, 0), headline, font=headline_font)
    detail_y = padding + headline_box[3] - headline_box[1] + max(4, padding // 2)
    draw.text(
        (padding + line_width, detail_y),
        detail,
        font=detail_font,
        fill=(255, 255, 255),
    )

    legend = "空心红圈：模型识别的疑似缺陷位置"
    legend_font = _fit_font(
        font_path,
        legend,
        max(13, int(round(width * 0.018))),
        max(1, width - 3 * padding - 24),
        minimum_size=11,
    )
    legend_y = top_height + height + max(4, padding // 2)
    marker_size = max(12, int(round(width * 0.014)))
    marker_center = (
        padding + marker_size // 2,
        legend_y + 2 + marker_size // 2,
    )
    draw.ellipse(
        (
            marker_center[0] - marker_size // 2,
            marker_center[1] - marker_size // 2,
            marker_center[0] + marker_size // 2,
            marker_center[1] + marker_size // 2,
        ),
        outline=(255, 0, 0),
        width=max(2, marker_size // 8),
    )
    draw.text(
        (padding + marker_size + max(6, padding // 2), legend_y),
        legend,
        font=legend_font,
        fill=(235, 235, 235),
    )

    return cv2.cvtColor(np.asarray(pil_image), cv2.COLOR_RGB2BGR)


def overlay_defect_on_image(
    original_path,
    defect_mask,
    predicted_class,
    confidence,
    output_path,
    overlay_alpha=0.38,
    max_dimension=1600,
    min_component_area=12,
    font_path=None,
    original_image=None,
):
    """Create a compact Chinese result image from an auditable raw mask."""

    confidence = _validate_prediction(predicted_class, confidence)
    if not 0.0 <= float(overlay_alpha) <= 1.0:
        raise ValueError("overlay_alpha must be from 0 to 1")
    if int(max_dimension) < 256:
        raise ValueError("max_dimension must be at least 256")

    mask = np.asarray(defect_mask)
    if mask.ndim != 2:
        raise ValueError("defect_mask must be a two-dimensional array")
    raw_has_defect = bool(np.any(mask > 0))
    display_mask, components = filter_display_components(
        mask,
        min_component_area=min_component_area,
    )
    status = build_visualization_status(
        predicted_class,
        confidence,
        raw_has_defect=raw_has_defect,
        component_count=len(components),
    )
    resolved_font = _resolve_font_path(font_path)
    if original_image is None:
        if original_path is None:
            raise ValueError("original_path 和 original_image 不能同时为空")
        original = _read_color_image(original_path)
    else:
        original = np.asarray(original_image)
        if original.ndim != 3 or original.shape[2] != 3:
            raise ValueError("original_image 必须是三通道彩色图像")
        if original.dtype != np.uint8:
            original = np.clip(original, 0, 255).astype(np.uint8)

    reference = min(int(max_dimension), max(original.shape[:2]))
    headline_size = max(18, int(round(reference * 0.028)))
    top_height = max(66, int(round(headline_size * 2.65)))
    bottom_height = max(38, int(round(headline_size * 1.15)))
    body = _resize_body(
        original,
        max_dimension=int(max_dimension),
        top_height=top_height,
        bottom_height=bottom_height,
    )

    if components:
        marked = _mark_components(
            body,
            display_mask,
            components,
            source_shape=mask.shape,
            overlay_alpha=overlay_alpha,
        )
    else:
        marked = body.copy()

    result = _draw_chinese_bars(
        marked,
        status,
        resolved_font,
        top_height=top_height,
        bottom_height=bottom_height,
    )
    output_path = Path(output_path)
    _write_png(output_path, result)
    return output_path
