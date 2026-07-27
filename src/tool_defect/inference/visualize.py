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
    """Draw precise contours plus numbered callouts on the image body."""

    height, width = image.shape[:2]
    resized_mask = cv2.resize(
        display_mask,
        (width, height),
        interpolation=cv2.INTER_NEAREST,
    )
    overlay = image.copy()
    overlay[resized_mask > 0] = (0, 0, 255)
    marked = cv2.addWeighted(
        image,
        1.0 - float(overlay_alpha),
        overlay,
        float(overlay_alpha),
        0,
    )

    contours, _ = cv2.findContours(
        resized_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    line_width = max(2, int(round(max(width, height) / 600)))
    cv2.drawContours(marked, contours, -1, (0, 0, 255), line_width)

    source_height, source_width = source_shape
    x_scale = width / float(source_width)
    y_scale = height / float(source_height)
    badge_radius = max(11, int(round(max(width, height) / 80)))
    badge_font_scale = max(0.45, badge_radius / 22)
    badge_thickness = max(1, line_width)

    for number, component in enumerate(components, start=1):
        center = (
            int(round(component.center_x * x_scale)),
            int(round(component.center_y * y_scale)),
        )
        component_width = max(1, int(round(component.width * x_scale)))
        component_height = max(1, int(round(component.height * y_scale)))
        callout_radius = max(
            badge_radius + 3,
            int(round(0.65 * max(component_width, component_height))),
        )
        cv2.circle(marked, center, callout_radius, (0, 0, 255), line_width)

        badge_center = (
            min(width - badge_radius, max(badge_radius, center[0])),
            min(
                height - badge_radius,
                max(badge_radius, center[1] - callout_radius),
            ),
        )
        cv2.circle(marked, badge_center, badge_radius, (0, 0, 255), -1)
        label = str(number)
        (text_width, text_height), _ = cv2.getTextSize(
            label,
            cv2.FONT_HERSHEY_SIMPLEX,
            badge_font_scale,
            badge_thickness,
        )
        text_origin = (
            badge_center[0] - text_width // 2,
            badge_center[1] + text_height // 2,
        )
        cv2.putText(
            marked,
            label,
            text_origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            badge_font_scale,
            (255, 255, 255),
            badge_thickness,
            cv2.LINE_AA,
        )
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

    legend = "红色区域和轮廓：模型识别的疑似缺陷位置"
    legend_font = _fit_font(
        font_path,
        legend,
        max(13, int(round(width * 0.018))),
        max(1, width - 3 * padding - 24),
        minimum_size=11,
    )
    legend_y = top_height + height + max(4, padding // 2)
    marker_size = max(12, int(round(width * 0.014)))
    draw.rectangle(
        (
            padding,
            legend_y + 2,
            padding + marker_size,
            legend_y + 2 + marker_size,
        ),
        fill=(255, 0, 0),
    )
    draw.text(
        (padding + marker_size + max(6, padding // 2), legend_y),
        legend,
        font=legend_font,
        fill=(235, 235, 235),
    )

    if status.component_count > 0:
        border_width = max(3, int(round(width / 400)))
        draw.rectangle(
            (0, top_height, width - 1, top_height + height - 1),
            outline=status_rgb,
            width=border_width,
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
    original = _read_color_image(original_path)

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
