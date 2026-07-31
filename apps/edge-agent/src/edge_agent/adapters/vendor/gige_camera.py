"""GigE Vision 相机适配器 — 实现 CameraAdapter 协议。"""

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
    pass  # GigE SDK 占位 — 替换为厂商 SDK 导入
    _GIGE_SDK_AVAILABLE = False
except ImportError:
    _GIGE_SDK_AVAILABLE = False


class _GigECameraAdapter:
    """GigE Vision 相机适配器。

    通过 vendor_config 字典配置连接参数。所有实际成像操作由 PENDING_HARDWARE
    守卫控制；守卫开启时不访问真实硬件。
    """

    def __init__(self, vendor_config: Mapping[str, Any]) -> None:
        self._config = dict(vendor_config)
        self._hardware_enabled = self._config.get("hardware_enabled") is True
        self._ip = self._config.get("ip", "")
        self._port = int(self._config.get("port", 3956))
        self._exposure_us = int(self._config.get("exposure_us", 5000))
        self._gain = float(self._config.get("gain", 0.0))
        self._trigger_mode = self._config.get("trigger_mode", "external")
        self._trigger_debounce_us = int(self._config.get("trigger_debounce_us", 100))
        self._trigger_delay_us = int(self._config.get("trigger_delay_us", 0))
        self._pixel_format = self._config.get("pixel_format", "Mono8")
        self._width = int(self._config.get("width", 2448))
        self._height = int(self._config.get("height", 2048))
        self._frame_rate = float(self._config.get("frame_rate", 10.0))
        self._connection_timeout_s = float(self._config.get("connection_timeout_s", 5.0))
        self._capture_timeout_s = float(self._config.get("capture_timeout_s", 3.0))
        self._device = None
        self._frame_count = 0
        self._last_frame_time: Optional[float] = None

        self._validate_config()

    def _validate_config(self) -> None:
        if "hardware_enabled" in self._config and not isinstance(
            self._config["hardware_enabled"], bool
        ):
            raise ValueError("GigE camera config: hardware_enabled must be boolean")
        if not self._ip:
            raise ValueError("GigE camera config: 'ip' is required")
        if self._port < 1 or self._port > 65535:
            raise ValueError(f"GigE camera config: invalid port {self._port}")
        if self._exposure_us < 10:
            raise ValueError(
                f"GigE camera config: exposure_us {self._exposure_us} too low"
            )
        if self._trigger_mode not in ("external", "internal", "software"):
            raise ValueError(
                f"GigE camera config: unknown trigger_mode '{self._trigger_mode}'"
            )
        if self._trigger_debounce_us < 0:
            raise ValueError("GigE camera config: trigger_debounce_us must be >= 0")

    def capture(self, trigger: TriggerEvent) -> Sequence[CapturedFrame]:
        if not self._hardware_enabled:
            raise CameraCaptureError(
                "PENDING_HARDWARE: GigE camera SDK not installed or hardware not "
                "available on this machine."
            )
        if not _GIGE_SDK_AVAILABLE:
            raise CameraCaptureError(
                "GigE Vision SDK is not installed on this machine."
            )

        try:
            return self._do_capture(trigger)
        except CameraBusyError:
            raise
        except CameraCaptureError:
            raise
        except Exception as exc:
            raise CameraCaptureError(
                f"GigE camera capture failed at {self._ip}:{self._port}: {exc}"
            ) from exc

    def _do_capture(self, trigger: TriggerEvent) -> Sequence[CapturedFrame]:
        if self._device is None:
            raise CameraCaptureError("GigE camera not connected")
        if self._device.is_busy():
            raise CameraBusyError(
                f"GigE camera at {self._ip}:{self._port} is busy"
            )

        acquisition_start = time.monotonic()
        raw = self._device.grab_frame(
            timeout_ms=int(self._capture_timeout_s * 1000)
        )
        if raw is None:
            raise CameraCaptureError(
                f"GigE camera at {self._ip}:{self._port} returned null frame"
            )

        elapsed = time.monotonic() - acquisition_start
        self._frame_count += 1
        self._last_frame_time = elapsed

        if not _NPY_AVAILABLE:
            content = raw.tobytes() if hasattr(raw, "tobytes") else b""
        else:
            content = raw if isinstance(raw, bytes) else raw.tobytes()

        frame = CapturedFrame(
            image_role="PRIMARY",
            content=content,
            media_type="image/png",
            extension="png",
            width=getattr(raw, "shape", (self._height, self._width))[1]
            if hasattr(raw, "shape")
            else self._width,
            height=getattr(raw, "shape", (self._height, self._width))[0]
            if hasattr(raw, "shape")
            else self._height,
            bit_depth=self._config.get("bit_depth"),
            channels=1 if self._pixel_format == "Mono8" else None,
            metadata={
                "vendor": "gige_vision",
                "ip": self._ip,
                "exposure_us": self._exposure_us,
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
            "adapter": "GigECameraAdapter",
            "ip": self._ip,
            "port": self._port,
            "frame_count": self._frame_count,
            "pending_hardware": not self._hardware_enabled,
            "sdk_available": _GIGE_SDK_AVAILABLE,
        }
        if not self._hardware_enabled:
            base["status"] = "PENDING_HARDWARE"
            base["message"] = "GigE SDK not installed or hardware not available"
            return base
        if not _GIGE_SDK_AVAILABLE:
            base["status"] = "SDK_MISSING"
            return base

        try:
            base["connected"] = self._device is not None
            base["frame_rate"] = self._frame_rate
            base["trigger_mode"] = self._trigger_mode
            if self._last_frame_time is not None:
                base["last_capture_time_s"] = round(self._last_frame_time, 6)
            base["status"] = "ONLINE" if self._device is not None else "OFFLINE"
        except Exception as exc:
            base["status"] = "ERROR"
            base["error"] = str(exc)
        return base


def create_gige_camera(vendor_config: Mapping[str, Any]) -> CameraAdapter:
    """创建 GigE Vision 相机适配器。"""
    return _GigECameraAdapter(vendor_config)
