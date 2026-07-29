"""受控图像解码器。"""

import cv2
import numpy as np

from tool_defect.plugin_api import ImageFrame, PluginError, PluginErrorCode

from inference_service.storage.materializer import MaterializedObject


class ImageDecoder:
    def __init__(self, *, maximum_pixels: int = 40_000_000):
        self._maximum_pixels = int(maximum_pixels)
        if self._maximum_pixels <= 0:
            raise ValueError("图片像素上限必须为正数")

    def decode(self, materialized: MaterializedObject) -> ImageFrame:
        try:
            encoded = np.fromfile(materialized.path, dtype=np.uint8)
            detected_media_type = _detect_media_type(encoded)
            declared_media_type = materialized.reference.media_type
            if detected_media_type != declared_media_type:
                raise PluginError.create(
                    PluginErrorCode.INPUT_INVALID,
                    "decode",
                    "图片内容与声明媒体类型不一致",
                    {
                        "declared": declared_media_type,
                        "detected": detected_media_type,
                    },
                )
            pixels = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        except PluginError:
            raise
        except Exception as error:
            raise PluginError.create(
                PluginErrorCode.INPUT_INVALID,
                "decode",
                "图片解码失败",
                {"exception_type": type(error).__name__},
            ) from error
        if pixels is None or not pixels.size:
            raise PluginError.create(
                PluginErrorCode.INPUT_INVALID,
                "decode",
                "图片无法解码",
            )
        height, width = pixels.shape[:2]
        if height * width > self._maximum_pixels:
            raise PluginError.create(
                PluginErrorCode.INPUT_INVALID,
                "decode",
                "图片解码尺寸超过限制",
                {"height": height, "width": width},
            )
        reference = materialized.reference
        if reference.width is not None and (
            reference.width != width or reference.height != height
        ):
            raise PluginError.create(
                PluginErrorCode.INPUT_INVALID,
                "decode",
                "图片解码尺寸与冻结对象引用不一致",
                {
                    "declared_width": reference.width,
                    "declared_height": reference.height,
                    "actual_width": width,
                    "actual_height": height,
                },
            )
        image_role = (
            reference.image_role.lower()
            if reference.image_role is not None
            else "primary"
        )
        return ImageFrame(
            image_id=reference.image_id,
            pixels=pixels,
            color_space="BGR",
            media_type=reference.media_type,
            sha256=materialized.sha256,
            original_height=height,
            original_width=width,
            attributes={
                "image_role": image_role,
                "image_kind": reference.kind,
            },
            encoded_bytes=encoded.tobytes(),
        )


def _detect_media_type(encoded: np.ndarray) -> str:
    header = np.asarray(encoded[:12], dtype=np.uint8).tobytes()
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"BM"):
        return "image/bmp"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    raise PluginError.create(
        PluginErrorCode.INPUT_INVALID,
        "decode",
        "图片格式不在允许列表",
    )
