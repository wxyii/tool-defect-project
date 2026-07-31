"""USB / UVC 相机适配器 — 实现 CameraAdapter 协议。"""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping, Optional, Sequence

from ..ports import CameraAdapter, CameraBusyError, CameraCaptureError, TriggerEvent
from ...capture.models import CapturedFrame

logger = logging.getLogger(__name__)

PENDING_HARDWARE = True

try:
    import numpy as np  # noqa: F401

    _NPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _NPY_AVAILABLE = False

try:
    import cv2  # noqa: F401

    _OPENCV_AVAILABLE = True
except ImportError:
    _OPENCV_AVAILABLE = False


class _USBCameraAdapter:
    """USB / UVC 相机适配器。

    通过 vendor_config 字典配置设备参数。所有实际成像操作由 PENDING_HARDWARE
    守卫控制。
    """

    def __init__(self, vendor_config: Mapping[str, Any]) -> None:
        self._config = dict(vendor_config)
        self._hardware_enabled = self._config.get("hardware_enabled") is True
        self._device_id = self._config.get("device_id", 0)
        self._width = int(self._config.get("width", 1920))
        self._height = int(self._config.get("height", 1080))
        self._target_fps = float(self._config.get("fps", 30.0))
        self._exposure = float(self._config.get("exposure", -1))
        self._gain = float(self._config.get("gain", 0.0))
        self._pixel_format = self._config.get("pixel_format", "BGR")
        self._capture_timeout_s = float(self._config.get("capture_timeout_s", 5.0))
        self._fourcc = self._config.get("fourcc", "MJPG")
        self._auto_exposure = self._config.get("auto_exposure", True)
        self._auto_white_balance = self._config.get("auto_white_balance", True)
        self._buffer_size = int(self._config.get("buffer_size", 1))
        self._cap: object = None
        self._frame_count = 0
        self._last_frame_time: Optional[float] = None
        self._fps_samples: list[float] = []

        self._validate_config()
        if self._hardware_enabled and _OPENCV_AVAILABLE:
            self._open_device()

    def _validate_config(self) -> None:
        if "hardware_enabled" in self._config and not isinstance(
            self._config["hardware_enabled"], bool
        ):
            raise ValueError("USB camera config: hardware_enabled must be boolean")
        if not isinstance(self._device_id, int) or self._device_id < 0:
            raise ValueError(
                f"USB camera config: device_id must be non-negative int, "
                f"got {self._device_id}"
            )
        if self._width < 1 or self._height < 1:
            raise ValueError(
                f"USB camera config: invalid resolution {self._width}x{self._height}"
            )
        if self._target_fps <= 0:
            raise ValueError(
                f"USB camera config: fps must be positive, got {self._target_fps}"
            )
        if self._capture_timeout_s <= 0:
            raise ValueError(
                f"USB camera config: capture_timeout_s must be positive, "
                f"got {self._capture_timeout_s}"
            )

    def _open_device(self) -> None:
        import cv2

        capture = cv2.VideoCapture(self._device_id)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        capture.set(cv2.CAP_PROP_FPS, self._target_fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, self._buffer_size)
        if not self._auto_exposure:
            capture.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
            capture.set(cv2.CAP_PROP_EXPOSURE, self._exposure)
        if not self._auto_white_balance:
            capture.set(cv2.CAP_PROP_AUTO_WB, 0)
        if len(str(self._fourcc)) == 4:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*str(self._fourcc)))
        self._cap = capture

    def capture(self, trigger: TriggerEvent) -> Sequence[CapturedFrame]:
        if not self._hardware_enabled:
            raise CameraCaptureError(
                "PENDING_HARDWARE: USB camera adapter cannot access real hardware."
            )
        if not _OPENCV_AVAILABLE:
            raise CameraCaptureError("OpenCV (cv2) is not installed on this machine.")

        try:
            return self._do_capture(trigger)
        except CameraBusyError:
            raise
        except CameraCaptureError:
            raise
        except Exception as exc:
            raise CameraCaptureError(
                f"USB camera capture failed on device {self._device_id}: {exc}"
            ) from exc

    def _do_capture(self, trigger: TriggerEvent) -> Sequence[CapturedFrame]:
        if self._cap is None or not self._cap.isOpened():
            raise CameraCaptureError(
                f"USB camera device {self._device_id} is not open"
            )

        acquisition_start = time.monotonic()
        grabbed, raw = self._cap.read()
        if not grabbed:
            raise CameraCaptureError(
                f"USB camera device {self._device_id} failed to read frame"
            )

        elapsed = time.monotonic() - acquisition_start
        self._frame_count += 1
        self._last_frame_time = elapsed
        self._fps_samples.append(1.0 / max(elapsed, 0.001))
        if len(self._fps_samples) > 60:
            self._fps_samples.pop(0)

        if _OPENCV_AVAILABLE:
            import cv2

            encoded_ok, encoded = cv2.imencode(
                ".png", raw, [cv2.IMWRITE_PNG_COMPRESSION, 0]
            )
            if not encoded_ok:
                raise CameraCaptureError("USB camera PNG encoding failed")
            content = encoded.tobytes()
        elif _NPY_AVAILABLE and hasattr(raw, "tobytes"):
            content = raw.tobytes()
        else:
            content = b""

        frame = CapturedFrame(
            image_role="PRIMARY",
            content=content,
            media_type="image/png",
            extension="png",
            width=raw.shape[1] if hasattr(raw, "shape") else self._width,
            height=raw.shape[0] if hasattr(raw, "shape") else self._height,
            channels=raw.shape[2] if hasattr(raw, "shape") and len(raw.shape) > 2 else 3,
            metadata={
                "vendor": "usb_uvc",
                "device_id": self._device_id,
                "exposure": self._exposure,
                "gain": self._gain,
                "trigger_id": trigger.trigger_id,
                "trigger_sequence": trigger.sequence,
                "acquisition_time_s": round(elapsed, 6),
                "pixel_format": self._pixel_format,
            },
        )
        return (frame,)

    def health(self) -> Mapping[str, object]:
        base = {
            "adapter": "USBCameraAdapter",
            "device_id": self._device_id,
            "resolution": f"{self._width}x{self._height}",
            "target_fps": self._target_fps,
            "frame_count": self._frame_count,
            "pending_hardware": not self._hardware_enabled,
            "opencv_available": _OPENCV_AVAILABLE,
        }
        if not self._hardware_enabled:
            base["status"] = "PENDING_HARDWARE"
            base["message"] = "USB camera adapter blocked by PENDING_HARDWARE guard"
            return base
        if not _OPENCV_AVAILABLE:
            base["status"] = "SDK_MISSING"
            base["message"] = "OpenCV not installed"
            return base

        try:
            if self._cap is not None and self._cap.isOpened():
                base["connected"] = True
                base["current_width"] = int(self._cap.get(3))
                base["current_height"] = int(self._cap.get(4))
                base["current_fps"] = int(self._cap.get(5))
                base["status"] = "ONLINE"
            else:
                base["connected"] = False
                base["status"] = "OFFLINE"
            if self._fps_samples:
                base["measured_fps"] = round(
                    sum(self._fps_samples) / len(self._fps_samples), 2
                )
        except Exception as exc:
            base["status"] = "ERROR"
            base["error"] = str(exc)
        return base


def create_usb_camera(vendor_config: Mapping[str, Any]) -> CameraAdapter:
    """创建 USB / UVC 相机适配器。"""
    return _USBCameraAdapter(vendor_config)
