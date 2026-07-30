"""触发去抖、序列检查和采集协调。"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Optional, Sequence
from uuid import uuid4

from ..adapters.ports import (
    CameraAdapter,
    CameraBusyError,
    CameraCaptureError,
    TriggerEvent,
)
from ..health.disk_watermark import DiskWatermarkController
from ..telemetry import MetricRegistry
from .models import CapturedFrame, PersistedCapture
from .storage import AtomicCaptureStore, CaptureStorageError


@dataclass(frozen=True)
class TriggerDecision:
    accepted: bool
    duplicate: bool
    warnings: tuple[str, ...]
    related_trigger_id: Optional[str] = None


class TriggerGuard:
    """按来源、序号和时间去抖，但不覆盖无法确认的触发。"""

    def __init__(self, debounce_seconds: float) -> None:
        if debounce_seconds < 0:
            raise ValueError("去抖窗口不能为负数")
        self.debounce_seconds = debounce_seconds
        self._last_by_source: dict[str, TriggerEvent] = {}
        self._seen_ids: set[tuple[str, str]] = set()

    def seed_previous(self, event: TriggerEvent) -> None:
        """只在进程内尚无游标时恢复持久化的最近触发。"""

        if event.source not in self._last_by_source:
            self._last_by_source[event.source] = event
            self._seen_ids.add((event.source, event.trigger_id))

    def evaluate(self, event: TriggerEvent) -> TriggerDecision:
        key = (event.source, event.trigger_id)
        previous = self._last_by_source.get(event.source)
        warnings: list[str] = []
        if key in self._seen_ids:
            return TriggerDecision(False, True, ("DUPLICATE_TRIGGER_ID",))
        if previous is not None:
            delta = event.occurred_monotonic - previous.occurred_monotonic
            if (
                event.sequence == previous.sequence
                and 0 <= delta <= self.debounce_seconds
            ):
                self._seen_ids.add(key)
                return TriggerDecision(
                    False,
                    True,
                    ("DEBOUNCED_TRIGGER",),
                    previous.trigger_id,
                )
            if event.sequence <= previous.sequence:
                warnings.append("TRIGGER_SEQUENCE_REGRESSION")
            elif event.sequence > previous.sequence + 1:
                warnings.append("TRIGGER_SEQUENCE_GAP")
        self._last_by_source[event.source] = event
        self._seen_ids.add(key)
        return TriggerDecision(
            True,
            False,
            tuple(warnings),
            previous.trigger_id if previous is not None and warnings else None,
        )


@dataclass(frozen=True)
class CaptureOutcome:
    status: str
    capture_id: Optional[str]
    persisted: Optional[PersistedCapture]
    warnings: tuple[str, ...]
    error_code: Optional[str] = None


class CaptureCoordinator:
    def __init__(
        self,
        *,
        camera: CameraAdapter,
        store: AtomicCaptureStore,
        trigger_guard: TriggerGuard,
        station_id: str,
        recipe_id: str,
        capture_id_factory: Callable[[], str] = lambda: str(uuid4()),
        camera_busy_retries: int = 1,
        disk_watermark: DiskWatermarkController | None = None,
        metrics: MetricRegistry | None = None,
    ) -> None:
        if camera_busy_retries < 0:
            raise ValueError("相机繁忙重试次数不能为负数")
        self.camera = camera
        self.store = store
        self.trigger_guard = trigger_guard
        self.station_id = station_id
        self.recipe_id = recipe_id
        self.capture_id_factory = capture_id_factory
        self.camera_busy_retries = camera_busy_retries
        self.disk_watermark = disk_watermark
        self.metrics = metrics

    def recover_incomplete_triggers(
        self,
        *,
        allow_recapture: bool = False,
    ) -> list[CaptureOutcome]:
        """启动时收口已领取但未完成的触发。

        默认不假设工件仍在相机视野内：能从目录/SQLite 恢复的事件会回填；
        无任何图片证据的事件显式进入需人工 HOLD 的本地事故。现场确认设备
        允许安全重采后，调用方才可设置 ``allow_recapture``。
        """

        outcomes: list[CaptureOutcome] = []
        for raw in self.store.queue.unfinished_triggers():
            event = TriggerEvent(
                trigger_id=str(raw["trigger_id"]),
                sequence=int(raw["sequence"]),
                occurred_at=str(raw["occurred_at"]),
                occurred_monotonic=float(raw["occurred_monotonic"]),
                source=str(raw["source"]),
            )
            capture_id = (
                str(raw["capture_id"])
                if raw["capture_id"] is not None
                else None
            )
            self.store.recover()
            if (
                capture_id is not None
                and self.store.queue.get_capture(capture_id) is not None
            ):
                outcomes.append(self.handle(event))
                continue
            if allow_recapture:
                outcomes.append(self.handle(event))
                continue
            outcome = CaptureOutcome(
                status="QUALITY_REJECTED",
                capture_id=capture_id,
                persisted=None,
                warnings=tuple(raw["warnings"]) + (
                    "CAPTURE_INTERRUPTED_REQUIRES_HOLD",
                ),
                error_code="TD-CAMERA-INTERRUPTED-001",
            )
            self._record_outcome(event, outcome)
            outcomes.append(outcome)
        return outcomes

    def handle(self, event: TriggerEvent) -> CaptureOutcome:
        if self.disk_watermark is not None:
            disk = self.disk_watermark.before_capture()
            if not disk.allow_capture:
                return CaptureOutcome(
                    status="PAUSED",
                    capture_id=None,
                    persisted=None,
                    warnings=(
                        "DISK_USAGE_UNKNOWN"
                        if disk.level == "UNKNOWN"
                        else "DISK_CRITICAL",
                    ),
                    error_code="TD-EDGE-DISK-CRITICAL-001",
                )
        resumed_after_crash = False
        existing = self.store.queue.get_trigger(
            source=event.source,
            trigger_id=event.trigger_id,
        )
        if existing is not None:
            capture_id = (
                str(existing["capture_id"])
                if existing["capture_id"] is not None
                else None
            )
            if (
                existing["outcome_status"] == "CAPTURE_STARTED"
                and capture_id is not None
            ):
                if (
                    int(existing["sequence"]) != event.sequence
                    or str(existing["occurred_at"]) != event.occurred_at
                ):
                    outcome = CaptureOutcome(
                        status="QUALITY_REJECTED",
                        capture_id=capture_id,
                        persisted=None,
                        warnings=("TRIGGER_ID_CONTENT_CONFLICT",),
                        error_code="TD-PLC-CONFLICT-001",
                    )
                    self._record_outcome(event, outcome)
                    return outcome
                # 先修复“目录已落盘、SQLite 未提交”的窗口；若仍无队列
                # 记录，则以同一 capture_id 重做相机步骤。
                self.store.recover()
                recovered_record = self.store.queue.get_capture(capture_id)
                if recovered_record is None:
                    decision = TriggerDecision(
                        True,
                        False,
                        tuple(existing["warnings"]) + (
                            "RESUMED_AFTER_CRASH",
                        ),
                    )
                    resumed_after_crash = True
                else:
                    recovered_warnings = recovered_record.quality_warnings
                    recovered_status = (
                        "OK"
                        if recovered_record.quality_status == "OK"
                        else f"QUALITY_{recovered_record.quality_status}"
                    )
                    if recovered_record.state.value == "LOCAL_DEAD":
                        recovered_status = "QUALITY_REJECTED"
                        recovered_warnings = recovered_warnings + (
                            "RECOVERY_INTEGRITY_FAILURE",
                        )
                    self.store.queue.finish_trigger(
                        source=event.source,
                        trigger_id=event.trigger_id,
                        outcome_status=recovered_status,
                        warnings=recovered_warnings,
                        error_code=recovered_record.error_code,
                    )
                    return CaptureOutcome(
                        status="DUPLICATE",
                        capture_id=capture_id,
                        persisted=None,
                        warnings=("DUPLICATE_TRIGGER_ID",),
                    )
            else:
                return CaptureOutcome(
                    status="DUPLICATE",
                    capture_id=capture_id,
                    persisted=None,
                    warnings=("DUPLICATE_TRIGGER_ID",),
                )
        if not resumed_after_crash:
            previous = self.store.queue.latest_claimed_trigger(
                source=event.source
            )
            if previous is not None:
                self.trigger_guard.seed_previous(
                    TriggerEvent(
                        trigger_id=str(previous["trigger_id"]),
                        sequence=int(previous["sequence"]),
                        occurred_at=str(previous["occurred_at"]),
                        occurred_monotonic=float(
                            previous["occurred_monotonic"]
                        ),
                        source=str(previous["source"]),
                    )
                )
            decision = self.trigger_guard.evaluate(event)
            if not decision.accepted:
                self.store.queue.claim_trigger(
                    source=event.source,
                    trigger_id=event.trigger_id,
                    sequence=event.sequence,
                    occurred_at=event.occurred_at,
                    occurred_monotonic=event.occurred_monotonic,
                    related_trigger_id=decision.related_trigger_id,
                    capture_id=None,
                    outcome_status="DUPLICATE",
                    warnings=decision.warnings,
                )
                return CaptureOutcome(
                    status="DUPLICATE",
                    capture_id=None,
                    persisted=None,
                    warnings=decision.warnings,
                )

            capture_id = self.capture_id_factory()
            if not self.store.queue.claim_trigger(
                source=event.source,
                trigger_id=event.trigger_id,
                sequence=event.sequence,
                occurred_at=event.occurred_at,
                occurred_monotonic=event.occurred_monotonic,
                related_trigger_id=decision.related_trigger_id,
                capture_id=capture_id,
                outcome_status="CAPTURE_STARTED",
                warnings=decision.warnings,
            ):
                return CaptureOutcome(
                    status="DUPLICATE",
                    capture_id=None,
                    persisted=None,
                    warnings=("DUPLICATE_TRIGGER_ID",),
                )
        assert capture_id is not None
        frames: Sequence[CapturedFrame] = ()
        for attempt in range(self.camera_busy_retries + 1):
            try:
                frames = self.camera.capture(event)
                break
            except CameraBusyError as error:
                if attempt >= self.camera_busy_retries:
                    outcome = CaptureOutcome(
                        status="QUALITY_REJECTED",
                        capture_id=capture_id,
                        persisted=None,
                        warnings=decision.warnings + ("CAMERA_BUSY",),
                        error_code=error.error_code,
                    )
                    self._record_outcome(event, outcome)
                    return outcome
            except CameraCaptureError as error:
                outcome = CaptureOutcome(
                    status="QUALITY_REJECTED",
                    capture_id=capture_id,
                    persisted=None,
                    warnings=decision.warnings + ("CAMERA_ERROR",),
                    error_code=error.error_code,
                )
                self._record_outcome(event, outcome)
                return outcome
        if not frames:
            outcome = CaptureOutcome(
                status="QUALITY_REJECTED",
                capture_id=capture_id,
                persisted=None,
                warnings=decision.warnings + ("NO_IMAGE",),
                error_code="TD-CAMERA-VALIDATION-001",
            )
            self._record_outcome(event, outcome)
            return outcome
        try:
            persisted = self.store.persist(
                capture_id=capture_id,
                station_id=self.station_id,
                recipe_id=self.recipe_id,
                client_sequence=event.sequence,
                occurred_at=event.occurred_at,
                frames=frames,
                trigger_id=event.trigger_id,
                trigger_source=event.source,
                quality_warnings=decision.warnings,
            )
        except (CaptureStorageError, OSError):
            outcome = CaptureOutcome(
                status="QUALITY_REJECTED",
                capture_id=capture_id,
                persisted=None,
                warnings=decision.warnings + ("IMAGE_INVALID",),
                error_code="TD-EDGE-INTEGRITY-001",
            )
            self._record_outcome(event, outcome)
            return outcome
        outcome = CaptureOutcome(
            status=(
                "OK"
                if persisted.quality.status == "OK"
                else f"QUALITY_{persisted.quality.status}"
            ),
            capture_id=capture_id,
            persisted=persisted,
            warnings=persisted.quality.warnings,
        )
        self._record_outcome(event, outcome)
        return outcome

    def _record_outcome(
        self,
        event: TriggerEvent,
        outcome: CaptureOutcome,
    ) -> None:
        self.store.queue.finish_trigger(
            source=event.source,
            trigger_id=event.trigger_id,
            outcome_status=outcome.status,
            warnings=outcome.warnings,
            error_code=outcome.error_code,
        )
        if self.metrics is not None:
            self.metrics.increment(
                "tool_defect_edge_captures_total",
                labels={
                    "station": self.station_id,
                    "result": outcome.status.lower(),
                },
            )
