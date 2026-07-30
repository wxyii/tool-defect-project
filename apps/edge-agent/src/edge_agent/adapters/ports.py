"""厂商无关的触发与相机端口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Protocol, Sequence

from ..capture.models import CapturedFrame


@dataclass(frozen=True)
class TriggerEvent:
    trigger_id: str
    sequence: int
    occurred_at: str
    occurred_monotonic: float
    source: str
    metadata: Mapping[str, object] = field(default_factory=dict)


class TriggerAdapter(Protocol):
    def poll(self) -> Optional[TriggerEvent]:
        """返回下一触发；没有事件时返回 `None`。"""


class CameraAdapter(Protocol):
    def capture(self, trigger: TriggerEvent) -> Sequence[CapturedFrame]:
        """按当前配方返回一张或多张带角色的原始帧。"""

    def health(self) -> Mapping[str, object]:
        """返回不含厂商凭据的设备健康摘要。"""


class CameraCaptureError(RuntimeError):
    error_code = "TD-CAMERA-INTERNAL-001"
    retryable = False


class CameraBusyError(CameraCaptureError):
    error_code = "TD-CAMERA-TRANSIENT-001"
    retryable = True
