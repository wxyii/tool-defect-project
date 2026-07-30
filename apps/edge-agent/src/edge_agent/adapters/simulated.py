"""确定性的 PLC/相机模拟器。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Iterable, Mapping, Optional, Sequence

from .ports import (
    CameraBusyError,
    CameraCaptureError,
    TriggerEvent,
)
from ..capture.models import CapturedFrame


class SimulatedTriggerAdapter:
    def __init__(self, events: Iterable[TriggerEvent]) -> None:
        self._events: Deque[TriggerEvent] = deque(events)

    def poll(self) -> Optional[TriggerEvent]:
        return self._events.popleft() if self._events else None


@dataclass(frozen=True)
class CameraScenario:
    kind: str
    frames: tuple[CapturedFrame, ...] = ()
    message: str = ""

    @classmethod
    def success(cls, *frames: CapturedFrame) -> "CameraScenario":
        return cls(kind="SUCCESS", frames=tuple(frames))

    @classmethod
    def busy(cls) -> "CameraScenario":
        return cls(kind="BUSY", message="模拟相机繁忙")

    @classmethod
    def no_image(cls) -> "CameraScenario":
        return cls(kind="NO_IMAGE", message="模拟相机无图")

    @classmethod
    def corrupt(cls) -> "CameraScenario":
        return cls(
            kind="SUCCESS",
            frames=(
                CapturedFrame(
                    image_role="PRIMARY",
                    content=b"not-an-image",
                    media_type="image/png",
                    width=32,
                    height=24,
                ),
            ),
        )


class SimulatedCameraAdapter:
    def __init__(self, scenarios: Iterable[CameraScenario]) -> None:
        self._scenarios: Deque[CameraScenario] = deque(scenarios)
        self.calls: list[str] = []

    def capture(self, trigger: TriggerEvent) -> Sequence[CapturedFrame]:
        self.calls.append(trigger.trigger_id)
        if not self._scenarios:
            raise CameraCaptureError("模拟器没有剩余场景")
        scenario = self._scenarios.popleft()
        if scenario.kind == "BUSY":
            raise CameraBusyError(scenario.message)
        if scenario.kind == "NO_IMAGE":
            return ()
        if scenario.kind != "SUCCESS":
            raise CameraCaptureError(scenario.message or scenario.kind)
        return scenario.frames

    def health(self) -> Mapping[str, object]:
        return {
            "status": "ONLINE",
            "queued_scenarios": len(self._scenarios),
            "captures": len(self.calls),
        }
