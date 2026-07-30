"""固定 80/90/95% 磁盘水位与安全动作。"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable


@dataclass(frozen=True)
class DiskWatermarkDecision:
    usage_ratio: float
    level: str
    allow_capture: bool
    accelerated_cleanup: bool
    cleaned_capture_count: int


class DiskWatermarkController:
    WARNING_RATIO = 0.80
    HIGH_RATIO = 0.90
    CRITICAL_RATIO = 0.95

    def __init__(
        self,
        *,
        usage_ratio: Callable[[], float],
        cleanup_confirmed: Callable[[], int],
    ) -> None:
        self._usage_ratio = usage_ratio
        self._cleanup_confirmed = cleanup_confirmed

    def before_capture(self) -> DiskWatermarkDecision:
        ratio = float(self._usage_ratio())
        if not math.isfinite(ratio) or not 0 <= ratio <= 1:
            # 无法可信读取磁盘状态时按严重水位安全失败。
            return DiskWatermarkDecision(
                usage_ratio=1.0,
                level="UNKNOWN",
                allow_capture=False,
                accelerated_cleanup=False,
                cleaned_capture_count=0,
            )
        if ratio >= self.CRITICAL_RATIO:
            return DiskWatermarkDecision(
                usage_ratio=ratio,
                level="CRITICAL",
                allow_capture=False,
                accelerated_cleanup=False,
                cleaned_capture_count=0,
            )
        if ratio >= self.HIGH_RATIO:
            cleaned = self._cleanup_confirmed()
            if isinstance(cleaned, bool) or not isinstance(cleaned, int):
                raise TypeError("清理回调必须返回已清理采集数量")
            if cleaned < 0:
                raise ValueError("已清理采集数量不能为负数")
            return DiskWatermarkDecision(
                usage_ratio=ratio,
                level="HIGH",
                allow_capture=True,
                accelerated_cleanup=True,
                cleaned_capture_count=cleaned,
            )
        return DiskWatermarkDecision(
            usage_ratio=ratio,
            level="WARNING" if ratio >= self.WARNING_RATIO else "NORMAL",
            allow_capture=True,
            accelerated_cleanup=False,
            cleaned_capture_count=0,
        )
