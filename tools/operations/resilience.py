"""P5 故障注入、积压和长期稳定性判定的确定性模型。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Iterable


class Outcome(StrEnum):
    PASS = "PASS"
    HOLD = "HOLD"
    FAILED = "FAILED"


class FaultKind(StrEnum):
    NETWORK = "NETWORK"
    DATABASE = "DATABASE"
    OBJECT_STORAGE = "OBJECT_STORAGE"
    GPU = "GPU"
    PROCESS = "PROCESS"
    CLOCK_SKEW = "CLOCK_SKEW"
    QUEUE_BACKLOG = "QUEUE_BACKLOG"
    DISK = "DISK"
    MONITORING = "MONITORING"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    initial_delay_ms: int
    maximum_delay_ms: int

    def delays(self) -> tuple[int, ...]:
        if self.max_attempts < 1:
            raise ValueError("最大尝试次数必须大于零")
        if self.initial_delay_ms <= 0 or self.maximum_delay_ms <= 0:
            raise ValueError("退避时间必须大于零")
        delays: list[int] = []
        delay = self.initial_delay_ms
        for _ in range(self.max_attempts - 1):
            delays.append(min(delay, self.maximum_delay_ms))
            delay = min(delay * 2, self.maximum_delay_ms)
        return tuple(delays)


@dataclass(frozen=True)
class AttemptResult:
    success: bool
    retryable: bool
    code: str


@dataclass(frozen=True)
class ExecutionResult:
    status: Outcome
    attempts: int
    delays_ms: tuple[int, ...]
    final_code: str


def execute_bounded(
    operation: Callable[[int], AttemptResult],
    policy: RetryPolicy,
) -> ExecutionResult:
    """执行有限重试；不可恢复错误立即失败，耗尽后进入 HOLD。"""

    delays = policy.delays()
    used_delays: list[int] = []
    final = AttemptResult(False, False, "NOT_EXECUTED")
    for attempt in range(1, policy.max_attempts + 1):
        final = operation(attempt)
        if final.success:
            return ExecutionResult(
                Outcome.PASS, attempt, tuple(used_delays), final.code
            )
        if not final.retryable:
            return ExecutionResult(
                Outcome.FAILED, attempt, tuple(used_delays), final.code
            )
        if attempt < policy.max_attempts:
            used_delays.append(delays[attempt - 1])
    return ExecutionResult(
        Outcome.HOLD, policy.max_attempts, tuple(used_delays), final.code
    )


def fault_outcome(kind: FaultKind, *, recovered: bool) -> Outcome:
    """技术故障在恢复验证前永不形成业务 PASS。"""

    if not recovered:
        return Outcome.HOLD
    if kind in {
        FaultKind.NETWORK,
        FaultKind.DATABASE,
        FaultKind.OBJECT_STORAGE,
        FaultKind.GPU,
        FaultKind.PROCESS,
        FaultKind.CLOCK_SKEW,
        FaultKind.QUEUE_BACKLOG,
        FaultKind.DISK,
        FaultKind.MONITORING,
    }:
        return Outcome.HOLD
    raise ValueError(f"未知故障：{kind}")


@dataclass(frozen=True)
class QueueSimulation:
    submitted: int
    completed: int
    duplicate_results: int
    lost_results: int
    peak_backlog: int
    final_backlog: int
    p95_latency_ticks: int


def simulate_queue(
    arrivals_per_tick: Iterable[int],
    *,
    service_per_tick: int,
    outage_ticks: set[int] | None = None,
) -> QueueSimulation:
    """确定性模拟积压和恢复，使用任务标识检查丢失与重复。"""

    if service_per_tick <= 0:
        raise ValueError("每周期处理能力必须大于零")
    outages = outage_ticks or set()
    arrival_list = tuple(arrivals_per_tick)
    queue: deque[tuple[int, int]] = deque()
    completed: list[int] = []
    latencies: list[int] = []
    submitted = 0
    peak = 0
    for tick, arrivals in enumerate(arrival_list):
        if arrivals < 0:
            raise ValueError("到达量不能为负数")
        for _ in range(arrivals):
            submitted += 1
            queue.append((submitted, tick))
        peak = max(peak, len(queue))
        if tick not in outages:
            for _ in range(min(service_per_tick, len(queue))):
                task_id, created_tick = queue.popleft()
                completed.append(task_id)
                latencies.append(tick - created_tick + 1)

    tick = len(arrival_list)
    while queue:
        for _ in range(min(service_per_tick, len(queue))):
            task_id, created_tick = queue.popleft()
            completed.append(task_id)
            latencies.append(tick - created_tick + 1)
        tick += 1
    unique = set(completed)
    sorted_latency = sorted(latencies)
    p95_index = max(0, (95 * len(sorted_latency) + 99) // 100 - 1)
    return QueueSimulation(
        submitted=submitted,
        completed=len(completed),
        duplicate_results=len(completed) - len(unique),
        lost_results=submitted - len(unique),
        peak_backlog=peak,
        final_backlog=0,
        p95_latency_ticks=sorted_latency[p95_index] if sorted_latency else 0,
    )
