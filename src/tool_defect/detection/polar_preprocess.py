"""极坐标展开图进入异常分析前的标准预处理。"""

import cv2
import numpy as np


DENOISE_CONFIG = {
    "algorithm": "fast_nl_means_colored",
    "luminance_strength": 7.0,
    "color_strength": 5.0,
    "template_window_size": 7,
    "search_window_size": 21,
}


def denoise_polar_image(image):
    """对极坐标图做保边降噪，并保持水平方向的首尾周期连续性。"""

    image = np.asarray(image)
    if image.dtype != np.uint8:
        raise ValueError("极坐标降噪仅支持 uint8 图像")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("极坐标降噪需要三通道彩色图像")
    if not image.size:
        raise ValueError("极坐标降噪不能处理空图像")

    radius = DENOISE_CONFIG["search_window_size"] // 2
    # 横轴是角度，0 度和 360 度实际相邻；先周期填充可避免在接缝处产生
    # 人工边缘。径向两端不是周期边界，因此使用反射填充。
    padded = np.pad(
        image,
        ((0, 0), (radius, radius), (0, 0)),
        mode="wrap",
    )
    padded = cv2.copyMakeBorder(
        padded,
        radius,
        radius,
        0,
        0,
        cv2.BORDER_REFLECT_101,
    )
    denoised = cv2.fastNlMeansDenoisingColored(
        padded,
        None,
        DENOISE_CONFIG["luminance_strength"],
        DENOISE_CONFIG["color_strength"],
        DENOISE_CONFIG["template_window_size"],
        DENOISE_CONFIG["search_window_size"],
    )
    return denoised[radius:-radius, radius:-radius].copy()


def analysis_polar_image(ring_result):
    """取得缓存中的降噪图；非缓存结果则即时执行同一套降噪。"""

    cached = getattr(ring_result, "denoised_polar_image", None)
    if cached is not None:
        return cached
    return denoise_polar_image(ring_result.polar_image)
