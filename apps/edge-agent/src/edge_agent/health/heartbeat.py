"""构建设备心跳，不包含图片、凭据或最终规则。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
import shutil
import time
from typing import Optional

from ..local_queue.database import EdgeQueue


class HeartbeatBuilder:
    def __init__(
        self,
        *,
        queue: EdgeQueue,
        data_root: Path | str,
        agent_version: str,
        camera_health: Callable[[], Mapping[str, object]],
        trigger_health: Callable[[], Mapping[str, object]],
        clock=time.time,
    ) -> None:
        self.queue = queue
        self.data_root = Path(data_root)
        self.agent_version = agent_version
        self.camera_health = camera_health
        self.trigger_health = trigger_health
        self.clock = clock

    def build(self, *, time_offset_ms: Optional[float]) -> dict[str, object]:
        if time_offset_ms is None:
            raise ValueError("时钟偏差未测量，不能伪装为 0")
        observed_at = self.clock()
        usage = shutil.disk_usage(self.data_root)
        camera_status = _device_status(self.camera_health(), "相机")
        plc_status = _device_status(self.trigger_health(), "触发器")
        return {
            "agent_version": self.agent_version,
            "reported_at": (
                datetime.fromtimestamp(observed_at, tz=timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            ),
            "queue_depth": self.queue.queue_depth(),
            "oldest_task_age_seconds": self.queue.oldest_unfinished_age_seconds(
                now=observed_at
            ),
            "disk_usage_ratio": (
                usage.used / usage.total if usage.total else 1.0
            ),
            "camera_status": camera_status,
            "plc_status": plc_status,
            "clock_offset_ms": time_offset_ms,
        }


def _device_status(health: Mapping[str, object], name: str) -> str:
    status = health.get("status")
    if status not in {"ONLINE", "OFFLINE", "DEGRADED"}:
        raise ValueError(f"{name}健康状态不属于冻结契约")
    return str(status)
