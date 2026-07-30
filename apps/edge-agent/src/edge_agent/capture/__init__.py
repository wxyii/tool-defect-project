"""采集质量对象与原子落盘。

协调器依赖硬件端口，为避免 `adapters -> capture.models -> capture`
形成循环，调用方从 `capture.coordinator` 显式导入协调器。
"""

from .models import CapturedFrame, FrameQuality, PersistedCapture
from .storage import AtomicCaptureStore, CaptureStorageError

__all__ = [
    "AtomicCaptureStore",
    "CapturedFrame",
    "CaptureStorageError",
    "FrameQuality",
    "PersistedCapture",
]
