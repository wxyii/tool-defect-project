"""配置化退避与抖动。"""

from __future__ import annotations

import random
from typing import Optional, Sequence


class BackoffPolicy:
    def __init__(
        self,
        delays_seconds: Sequence[float] = (1, 5, 30, 120, 600),
        *,
        steady_delay_seconds: float = 900,
        jitter_ratio: float = 0.2,
        random_source: Optional[random.Random] = None,
    ) -> None:
        if not delays_seconds or any(delay <= 0 for delay in delays_seconds):
            raise ValueError("退避间隔必须为正数")
        if steady_delay_seconds <= 0:
            raise ValueError("稳态退避必须为正数")
        if not 0 <= jitter_ratio < 1:
            raise ValueError("抖动比例必须位于 [0, 1)")
        self.delays_seconds = tuple(float(delay) for delay in delays_seconds)
        self.steady_delay_seconds = float(steady_delay_seconds)
        self.jitter_ratio = jitter_ratio
        self.random_source = random_source or random.Random()

    def delay_seconds(
        self,
        retry_count: int,
        *,
        retry_after_seconds: Optional[float] = None,
    ) -> float:
        if retry_count < 0:
            raise ValueError("重试次数不能为负数")
        retry_after_floor: Optional[float] = None
        if retry_after_seconds is not None:
            if retry_after_seconds < 0:
                raise ValueError("Retry-After 不能为负数")
            base = float(retry_after_seconds)
            retry_after_floor = base
        elif retry_count < len(self.delays_seconds):
            base = self.delays_seconds[retry_count]
        else:
            base = self.steady_delay_seconds
        if self.jitter_ratio == 0:
            return base
        factor = self.random_source.uniform(
            1 - self.jitter_ratio,
            1 + self.jitter_ratio,
        )
        jittered = max(0.0, base * factor)
        if retry_after_floor is not None:
            return max(retry_after_floor, jittered)
        return jittered
