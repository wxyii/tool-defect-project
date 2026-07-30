"""硬件适配端口和可重复模拟器。"""

from .ports import (
    CameraAdapter,
    CameraBusyError,
    CameraCaptureError,
    TriggerAdapter,
    TriggerEvent,
)
from .simulated import CameraScenario, SimulatedCameraAdapter, SimulatedTriggerAdapter

__all__ = [
    "CameraAdapter",
    "CameraBusyError",
    "CameraCaptureError",
    "CameraScenario",
    "SimulatedCameraAdapter",
    "SimulatedTriggerAdapter",
    "TriggerAdapter",
    "TriggerEvent",
]
