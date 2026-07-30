"""幂等同步状态机。

每次 `run_once` 只做有限工作，调用方负责调度；网络失败不会阻塞新采集。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import time
from typing import Callable, Mapping, Optional, Protocol, Sequence
from uuid import uuid4

from ..local_queue.database import EdgeQueue, QueueIntegrityError
from ..local_queue.models import CaptureRecord, LocalCaptureState, LocalImageRecord
from ..telemetry import JsonTelemetry, MetricRegistry
from .backoff import BackoffPolicy


@dataclass(frozen=True)
class UploadTicket:
    image_id: str
    image_role: str
    url: str
    method: str
    headers: Mapping[str, str]
    expires_at: float


@dataclass(frozen=True)
class CaptureInitialization:
    capture_id: str
    central_status: str
    upload_tickets: tuple[UploadTicket, ...]


@dataclass(frozen=True)
class DetectionSubmission:
    capture_id: str
    detection_task_id: str
    pipeline_version: str
    poll_after_ms: int


@dataclass(frozen=True)
class CentralCapture:
    capture_id: str
    capture_status: str
    business_disposition: Optional[str]
    poll_after_ms: int = 0
    error_code: Optional[str] = None


class SyncClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: Optional[int] = None,
        retryable: bool,
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class EdgeBusinessClient(Protocol):
    """生成客户端之上的窄封装。"""

    def initialize_capture(
        self,
        *,
        capture: CaptureRecord,
        images: Sequence[LocalImageRecord],
        idempotency_key: str,
        request_id: str,
    ) -> CaptureInitialization: ...

    def renew_upload_ticket(
        self,
        *,
        capture_id: str,
        image: LocalImageRecord,
        idempotency_key: str,
        request_id: str,
    ) -> UploadTicket: ...

    def upload_image(
        self,
        *,
        ticket: UploadTicket,
        file_path: Path,
        sha256: str,
        size_bytes: int,
    ) -> str: ...

    def complete_image(
        self,
        *,
        capture_id: str,
        image_id: str,
        sha256: str,
        size_bytes: int,
        upload_receipt: str,
        idempotency_key: str,
        request_id: str,
    ) -> None: ...

    def submit_detection(
        self,
        *,
        capture_id: str,
        idempotency_key: str,
        request_id: str,
    ) -> DetectionSubmission: ...

    def get_capture(
        self,
        *,
        capture_id: str,
        request_id: str,
    ) -> CentralCapture: ...

    def reconcile_captures(
        self,
        *,
        capture_ids: Sequence[str],
        request_id: str,
    ) -> Sequence[CentralCapture]: ...

    def send_heartbeat(
        self,
        *,
        device_id: str,
        payload: Mapping[str, object],
        idempotency_key: str,
        request_id: str,
    ) -> None: ...


class SyncService:
    def __init__(
        self,
        *,
        queue: EdgeQueue,
        client: EdgeBusinessClient,
        data_root: Path | str,
        backoff: BackoffPolicy,
        clock=time.time,
        request_id_factory=lambda: str(uuid4()),
        final_result_handler: Callable[[CentralCapture], None],
        confirmed_handler: Callable[[str], None],
        telemetry: JsonTelemetry | None = None,
        metrics: MetricRegistry | None = None,
    ) -> None:
        self.queue = queue
        self.client = client
        self.data_root = Path(data_root)
        self.backoff = backoff
        self.clock = clock
        self.request_id_factory = request_id_factory
        self.final_result_handler = final_result_handler
        self.confirmed_handler = confirmed_handler
        self.telemetry = telemetry
        self.metrics = metrics or MetricRegistry(
            {"result", "error_category"}
        )
        self._tickets: dict[tuple[str, str], UploadTicket] = {}

    def run_once(self, *, limit: int = 100) -> dict[str, list[str]]:
        if self.auth_pause_active:
            return {
                "succeeded": [],
                "retried": [],
                "failed": [],
                "paused": [],
            }
        self._retry_pending_confirmations()
        succeeded: list[str] = []
        retried: list[str] = []
        failed: list[str] = []
        paused: list[str] = []
        for record in self.queue.due_captures(now=self.clock(), limit=limit):
            traceparent = _capture_traceparent(
                record.capture_id,
                f"{record.state.value}:{record.retry_count}",
            )
            self._emit(
                "sync.started",
                "开始同步采集事件",
                traceparent=traceparent,
                capture_id=record.capture_id,
                station_id=record.station_id,
                result="STARTED",
            )
            try:
                self._process(record)
                succeeded.append(record.capture_id)
                self.metrics.increment(
                    "tool_defect_edge_sync_attempts_total",
                    labels={"result": "success", "error_category": "none"},
                )
                self._emit(
                    "sync.completed",
                    "采集事件同步步骤完成",
                    traceparent=traceparent,
                    capture_id=record.capture_id,
                    station_id=record.station_id,
                    result="SUCCESS",
                )
            except SyncClientError as error:
                if _is_global_auth_failure(error):
                    self._pause_for_auth(error)
                    paused.append(record.capture_id)
                    self._record_failure(
                        record,
                        error,
                        "paused",
                        traceparent,
                    )
                    break
                if error.retryable:
                    current = self.queue.get_capture(record.capture_id)
                    assert current is not None
                    delay = self.backoff.delay_seconds(
                        current.retry_count,
                        retry_after_seconds=error.retry_after_seconds,
                    )
                    self.queue.schedule_retry(
                        record.capture_id,
                        retry_at=self.clock() + delay,
                        error_code=error.code,
                    )
                    retried.append(record.capture_id)
                    self._record_failure(
                        record,
                        error,
                        "retry",
                        traceparent,
                    )
                else:
                    self.queue.transition(
                        record.capture_id,
                        LocalCaptureState.LOCAL_DEAD,
                        error_code=error.code,
                    )
                    failed.append(record.capture_id)
                    self._record_failure(
                        record,
                        error,
                        "dead",
                        traceparent,
                    )
            except (OSError, TimeoutError) as error:
                current = self.queue.get_capture(record.capture_id)
                assert current is not None
                delay = self.backoff.delay_seconds(current.retry_count)
                self.queue.schedule_retry(
                    record.capture_id,
                    retry_at=self.clock() + delay,
                    error_code="TD-EDGE-TRANSIENT-001",
                )
                retried.append(record.capture_id)
                self._record_failure(
                    record,
                    SyncClientError(
                        "本地或网络瞬时故障",
                        code="TD-EDGE-TRANSIENT-001",
                        retryable=True,
                    ),
                    "retry",
                    traceparent,
                )
        return {
            "succeeded": succeeded,
            "retried": retried,
            "failed": failed,
            "paused": paused,
        }

    def _record_failure(
        self,
        record: CaptureRecord,
        error: SyncClientError,
        result: str,
        traceparent: str,
    ) -> None:
        parts = error.code.split("-")
        category = parts[2].lower() if len(parts) >= 4 else "unknown"
        self.metrics.increment(
            "tool_defect_edge_sync_attempts_total",
            labels={"result": result, "error_category": category},
        )
        self._emit(
            "sync.failed",
            "采集事件同步步骤失败",
            level="ERROR" if not error.retryable else "WARNING",
            traceparent=traceparent,
            capture_id=record.capture_id,
            station_id=record.station_id,
            result=result.upper(),
            error_code=error.code,
            retryable=error.retryable,
            attempt_count=record.retry_count + 1,
        )

    def _emit(
        self,
        event: str,
        message: str,
        *,
        traceparent: str,
        level: str = "INFO",
        **fields: object,
    ) -> None:
        if self.telemetry is not None:
            self.telemetry.emit(
                event,
                message,
                level=level,
                traceparent=traceparent,
                **fields,
            )

    def reconcile(self, *, limit: int = 200) -> list[str]:
        self._require_auth_not_paused()
        self._retry_pending_confirmations()
        if not 1 <= limit <= 200:
            raise ValueError("对账批次必须位于冻结契约的 1..200")
        candidate_ids = self.queue.unfinished_capture_ids(limit=limit + 1)
        has_more = len(candidate_ids) > limit
        capture_ids = candidate_ids[:limit]
        if not capture_ids:
            return []
        request_id = self.request_id_factory()
        try:
            central_items = self.client.reconcile_captures(
                capture_ids=capture_ids,
                request_id=request_id,
            )
        except SyncClientError as error:
            if _is_global_auth_failure(error):
                self._pause_for_auth(error)
            raise
        advanced: list[str] = []
        requested = set(capture_ids)
        returned: set[str] = set()
        for item in central_items:
            if item.capture_id not in requested:
                raise QueueIntegrityError("中心返回了未请求的 capture_id")
            if item.capture_id in returned:
                raise QueueIntegrityError("中心对账响应包含重复 capture_id")
            returned.add(item.capture_id)
            if self._advance_from_central(item):
                advanced.append(item.capture_id)
        self.queue.set_agent_state("last_reconcile_at", self.clock())
        if returned == requested and not has_more:
            self.queue.set_cleanup_enabled(True)
        return advanced

    def send_heartbeat(
        self,
        *,
        device_id: str,
        payload: Mapping[str, object],
    ) -> None:
        self._require_auth_not_paused()
        request_id = self.request_id_factory()
        try:
            self.client.send_heartbeat(
                device_id=device_id,
                payload=payload,
                idempotency_key=f"{device_id}:heartbeat:{request_id}",
                request_id=request_id,
            )
        except SyncClientError as error:
            if _is_global_auth_failure(error):
                self._pause_for_auth(error)
            raise

    @property
    def auth_pause_active(self) -> bool:
        raw = self.queue.get_agent_state("sync_auth_pause")
        return isinstance(raw, dict) and raw.get("active") is True

    def resume_after_auth_recovery(self) -> None:
        self.queue.set_agent_state(
            "sync_auth_pause",
            {
                "active": False,
                "resumed_at": self.clock(),
            },
        )

    def _pause_for_auth(self, error: SyncClientError) -> None:
        self.queue.set_agent_state(
            "sync_auth_pause",
            {
                "active": True,
                "error_code": error.code,
                "paused_at": self.clock(),
            },
        )

    def _require_auth_not_paused(self) -> None:
        if self.auth_pause_active:
            raise SyncClientError(
                "同步因身份或证书故障暂停，需验证恢复后显式解除",
                code="TD-AUTH-PAUSED-001",
                retryable=False,
            )

    def _process(self, record: CaptureRecord) -> None:
        if record.state is LocalCaptureState.RETRY_WAIT:
            if record.resume_state is None:
                raise QueueIntegrityError("RETRY_WAIT 缺少恢复状态")
            record = self.queue.transition(record.capture_id, record.resume_state)

        if record.state is LocalCaptureState.PENDING:
            self._initialize(record)
            return
        if record.state is LocalCaptureState.UPLOADING:
            self._upload(record)
            return
        if record.state is LocalCaptureState.UPLOADED:
            self._submit(record)
            return
        if record.state is LocalCaptureState.SUBMITTED:
            record = self.queue.transition(
                record.capture_id,
                LocalCaptureState.WAIT_RESULT,
                expected=LocalCaptureState.SUBMITTED,
            )
            first_poll_at = self.queue.get_agent_state(
                f"first_poll_at:{record.capture_id}"
            )
            if isinstance(first_poll_at, (int, float)):
                self.queue.defer_poll(
                    record.capture_id,
                    next_poll_at=max(self.clock(), float(first_poll_at)),
                )
            return
        if record.state is LocalCaptureState.WAIT_RESULT:
            request_id = self.request_id_factory()
            central = self.client.get_capture(
                capture_id=record.capture_id,
                request_id=request_id,
            )
            if central.capture_id != record.capture_id:
                raise SyncClientError(
                    "轮询响应 capture_id 与请求不一致",
                    code="TD-API-INCOMPATIBLE-001",
                    retryable=False,
                )
            self._advance_from_central(central)
            return
        raise QueueIntegrityError(f"不支持同步状态：{record.state.value}")

    def _initialize(self, record: CaptureRecord) -> None:
        request_id = self.request_id_factory()
        operation = "INITIALIZE"
        self.queue.record_sync_start(
            request_id=request_id,
            capture_id=record.capture_id,
            operation=operation,
        )
        try:
            images = self.queue.list_images(record.capture_id)
            response = self.client.initialize_capture(
                capture=record,
                images=images,
                idempotency_key=(
                    f"{record.station_id}:{record.capture_id}:create"
                ),
                request_id=request_id,
            )
            if response.capture_id != record.capture_id:
                raise SyncClientError(
                    "中心 capture_id 不一致",
                    code="TD-API-CONFLICT-001",
                    status_code=409,
                    retryable=False,
                )
            by_role = {ticket.image_role: ticket for ticket in response.upload_tickets}
            if set(by_role) != {image.image_role for image in images}:
                raise SyncClientError(
                    "中心上传票据与本地图片不一致",
                    code="TD-API-INTEGRITY-001",
                    retryable=False,
                )
            for image in images:
                ticket = by_role[image.image_role]
                self._tickets[(record.capture_id, image.image_role)] = ticket
                self.queue.update_image_upload(
                    capture_id=record.capture_id,
                    image_role=image.image_role,
                    status="PENDING",
                    central_image_id=ticket.image_id,
                )
            self.queue.transition(
                record.capture_id,
                LocalCaptureState.UPLOADING,
                expected=LocalCaptureState.PENDING,
                central_status=response.central_status,
            )
            self.queue.record_sync_finish(request_id=request_id, result="SUCCESS")
        except BaseException as error:
            self.queue.record_sync_finish(
                request_id=request_id,
                result="FAILURE",
                error_code=getattr(error, "code", "TD-EDGE-INTERNAL-001"),
            )
            raise

    def _upload(self, record: CaptureRecord) -> None:
        images = self.queue.list_images(record.capture_id)
        for image in images:
            if image.upload_status == "AVAILABLE":
                continue
            upload_receipt = image.upload_receipt
            central_image_id = image.central_image_id
            if image.upload_status != "UPLOADED":
                ticket_key = (record.capture_id, image.image_role)
                ticket = self._tickets.get(ticket_key)
                if ticket is None or ticket.expires_at <= self.clock():
                    ticket = self.client.renew_upload_ticket(
                        capture_id=record.capture_id,
                        image=image,
                        idempotency_key=(
                            f"{record.station_id}:{record.capture_id}:"
                            f"{image.central_image_id or image.image_role}:"
                            f"ticket:{record.retry_count}"
                        ),
                        request_id=self.request_id_factory(),
                    )
                    self._tickets[ticket_key] = ticket
                central_image_id = ticket.image_id
                file_path = self.data_root / image.relative_path
                if not file_path.is_file():
                    raise SyncClientError(
                        "本地原图缺失",
                        code="TD-EDGE-INTEGRITY-002",
                        retryable=False,
                    )
                self.queue.update_image_upload(
                    capture_id=record.capture_id,
                    image_role=image.image_role,
                    status="UPLOADING",
                )
                try:
                    upload_receipt = self.client.upload_image(
                        ticket=ticket,
                        file_path=file_path,
                        sha256=image.sha256,
                        size_bytes=image.size_bytes,
                    )
                except SyncClientError as error:
                    if error.status_code in {401, 403}:
                        self._tickets.pop(ticket_key, None)
                        raise SyncClientError(
                            "上传授权已失效，下一次重试必须续期",
                            code="TD-UPLOAD-TICKET-EXPIRED",
                            status_code=error.status_code,
                            retryable=True,
                            retry_after_seconds=error.retry_after_seconds,
                        ) from error
                    raise
                if not upload_receipt:
                    raise SyncClientError(
                        "对象上传缺少持久化回执",
                        code="TD-EDGE-INTEGRITY-004",
                        retryable=False,
                    )
                self.queue.update_image_upload(
                    capture_id=record.capture_id,
                    image_role=image.image_role,
                    status="UPLOADED",
                    upload_receipt=upload_receipt,
                )
            elif central_image_id is None:
                raise SyncClientError(
                    "待确认图片缺少中心 image_id",
                    code="TD-EDGE-INTEGRITY-004",
                    retryable=False,
                )
            if not upload_receipt:
                raise SyncClientError(
                    "待确认图片缺少上传回执",
                    code="TD-EDGE-INTEGRITY-004",
                    retryable=False,
                )
            try:
                self.client.complete_image(
                    capture_id=record.capture_id,
                    image_id=central_image_id,
                    sha256=image.sha256,
                    size_bytes=image.size_bytes,
                    upload_receipt=upload_receipt,
                    idempotency_key=(
                        f"{record.capture_id}:{central_image_id}:complete"
                    ),
                    request_id=self.request_id_factory(),
                )
            except SyncClientError as error:
                if error.code == "TD-STORAGE-INTEGRITY-001":
                    retry_key = (
                        f"integrity_reupload:{record.capture_id}:"
                        f"{image.image_role}"
                    )
                    attempts = self.queue.get_agent_state(retry_key)
                    if attempts is None:
                        attempts = 0
                    if not isinstance(attempts, int) or isinstance(
                        attempts,
                        bool,
                    ):
                        raise QueueIntegrityError(
                            "图片完整性重传计数损坏"
                        )
                    if attempts < 1:
                        self.queue.set_agent_state(retry_key, attempts + 1)
                        self.queue.invalidate_image_upload(
                            capture_id=record.capture_id,
                            image_role=image.image_role,
                        )
                        self._tickets.pop(
                            (record.capture_id, image.image_role),
                            None,
                        )
                        raise SyncClientError(
                            "中心完整性校验失败，按策略仅重传一次",
                            code="TD-STORAGE-INTEGRITY-001",
                            status_code=error.status_code,
                            retryable=True,
                        ) from error
                    raise SyncClientError(
                        "中心完整性校验重复失败，停止自动重传",
                        code="TD-STORAGE-INTEGRITY-001",
                        status_code=error.status_code,
                        retryable=False,
                    ) from error
                if error.code == "TD-STORAGE-EXPIRED-001":
                    self.queue.invalidate_image_upload(
                        capture_id=record.capture_id,
                        image_role=image.image_role,
                    )
                    self._tickets.pop(
                        (record.capture_id, image.image_role),
                        None,
                    )
                    raise SyncClientError(
                        "上传会话在确认前过期，必须续票并重传",
                        code="TD-STORAGE-EXPIRED-001",
                        status_code=error.status_code,
                        retryable=True,
                    ) from error
                raise
            self.queue.update_image_upload(
                capture_id=record.capture_id,
                image_role=image.image_role,
                status="AVAILABLE",
                central_image_id=central_image_id,
            )
        self.queue.transition(
            record.capture_id,
            LocalCaptureState.UPLOADED,
            expected=LocalCaptureState.UPLOADING,
        )

    def _submit(self, record: CaptureRecord) -> None:
        response = self.client.submit_detection(
            capture_id=record.capture_id,
            idempotency_key=f"{record.capture_id}:submit",
            request_id=self.request_id_factory(),
        )
        if response.capture_id != record.capture_id:
            raise SyncClientError(
                "提交响应 capture_id 不一致",
                code="TD-API-CONFLICT-002",
                status_code=409,
                retryable=False,
            )
        if not 100 <= response.poll_after_ms <= 60_000:
            raise SyncClientError(
                "提交响应 poll_after_ms 超出冻结契约",
                code="TD-API-INCOMPATIBLE-003",
                retryable=False,
            )
        self.queue.set_agent_state(
            f"detection:{record.capture_id}",
            {
                "detection_task_id": response.detection_task_id,
                "pipeline_version": response.pipeline_version,
            },
        )
        self.queue.set_agent_state(
            f"first_poll_at:{record.capture_id}",
            self.clock() + response.poll_after_ms / 1_000,
        )
        self.queue.transition(
            record.capture_id,
            LocalCaptureState.SUBMITTED,
            expected=LocalCaptureState.UPLOADED,
            central_status="SUBMITTED",
        )

    def _advance_from_central(self, central: CentralCapture) -> bool:
        record = self.queue.get_capture(central.capture_id)
        if record is None:
            return False
        original_state = record.state
        if record.state is LocalCaptureState.RETRY_WAIT:
            if record.resume_state is None:
                raise QueueIntegrityError("RETRY_WAIT 缺少恢复状态")
            record = self.queue.transition(central.capture_id, record.resume_state)

        target = _CENTRAL_TO_LOCAL.get(central.capture_status)
        if target is None:
            raise SyncClientError(
                f"未知中心状态：{central.capture_status}",
                code="TD-API-INCOMPATIBLE-001",
                retryable=False,
            )
        if not 0 <= central.poll_after_ms <= 900_000:
            raise SyncClientError(
                "中心响应 poll_after_ms 超出冻结契约",
                code="TD-API-INCOMPATIBLE-003",
                retryable=False,
            )
        if central.capture_status == "FAILED":
            if central.business_disposition != "HOLD":
                raise SyncClientError(
                    "中心 FAILED 状态必须安全处置为 HOLD",
                    code="TD-API-INCOMPATIBLE-002",
                    retryable=False,
                )
        elif central.capture_status == "FINALIZED":
            if central.business_disposition not in {"PASS", "FAIL", "HOLD"}:
                raise SyncClientError(
                    "中心 FINALIZED 响应缺少合法业务处置",
                    code="TD-API-INCOMPATIBLE-002",
                    retryable=False,
                )
        elif central.business_disposition not in {None, "HOLD"}:
            raise SyncClientError(
                "中心非最终状态不得提前给出 PASS 或 FAIL",
                code="TD-API-INCOMPATIBLE-002",
                retryable=False,
            )
        if (
            record.state is LocalCaptureState.PENDING
            and target is LocalCaptureState.UPLOADING
            and any(
                image.central_image_id is None
                for image in self.queue.list_images(central.capture_id)
            )
        ):
            # SQLite 从清单重建后没有中心 image_id。保留 PENDING，让
            # 下一轮以原 capture_id 幂等重放 create 并取回票据，不能
            # 直接推进到一个必然无法续票的 UPLOADING。
            self.queue.transition(
                central.capture_id,
                LocalCaptureState.PENDING,
                central_status=central.capture_status,
                error_code=central.error_code,
            )
            return False
        while record.state is not target:
            next_state = _next_local_state(record.state, target)
            if next_state is None:
                # 中心落后时不回退本地投影。
                break
            if next_state is LocalCaptureState.DONE:
                try:
                    # 处理器必须以 capture_id 幂等。投递失败时不能先落
                    # DONE，否则最终处置会永久丢失。
                    self.final_result_handler(central)
                except Exception as error:
                    raise SyncClientError(
                        "最终处置投递失败",
                        code="TD-EDGE-FINAL-DELIVERY-001",
                        retryable=True,
                    ) from error
                self._add_pending_confirmation(central.capture_id)
            record = self.queue.transition(
                central.capture_id,
                next_state,
                central_status=central.capture_status,
                error_code=central.error_code,
            )
            if next_state is LocalCaptureState.DONE:
                self._try_confirmation(central.capture_id)
        if record.state is LocalCaptureState.WAIT_RESULT and target is record.state:
            self.queue.defer_poll(
                central.capture_id,
                next_poll_at=self.clock() + max(0, central.poll_after_ms) / 1_000,
            )
        return record.state is not original_state

    def _pending_confirmations(self) -> list[str]:
        raw = self.queue.get_agent_state("pending_confirmations")
        if raw is None:
            return []
        if not isinstance(raw, list) or not all(
            isinstance(item, str) for item in raw
        ):
            raise QueueIntegrityError("pending_confirmations 本地状态损坏")
        return list(dict.fromkeys(raw))

    def _add_pending_confirmation(self, capture_id: str) -> None:
        pending = self._pending_confirmations()
        if capture_id not in pending:
            pending.append(capture_id)
            self.queue.set_agent_state("pending_confirmations", pending)

    def _try_confirmation(self, capture_id: str) -> None:
        try:
            self.confirmed_handler(capture_id)
        except Exception:
            # DONE 之前已持久化待办；下一调度周期继续确认目录。
            return
        pending = [
            item for item in self._pending_confirmations() if item != capture_id
        ]
        self.queue.set_agent_state("pending_confirmations", pending)

    def _retry_pending_confirmations(self) -> None:
        for capture_id in self._pending_confirmations():
            record = self.queue.get_capture(capture_id)
            if record is not None and record.state is LocalCaptureState.DONE:
                self._try_confirmation(capture_id)


_CENTRAL_TO_LOCAL = {
    "CREATED": LocalCaptureState.PENDING,
    "UPLOADING": LocalCaptureState.UPLOADING,
    "READY": LocalCaptureState.UPLOADED,
    "SUBMITTED": LocalCaptureState.SUBMITTED,
    "PROCESSING": LocalCaptureState.WAIT_RESULT,
    "REVIEW_PENDING": LocalCaptureState.WAIT_RESULT,
    "FINALIZED": LocalCaptureState.DONE,
    "FAILED": LocalCaptureState.DONE,
}

_LOCAL_ORDER = (
    LocalCaptureState.PENDING,
    LocalCaptureState.UPLOADING,
    LocalCaptureState.UPLOADED,
    LocalCaptureState.SUBMITTED,
    LocalCaptureState.WAIT_RESULT,
    LocalCaptureState.DONE,
)


def _next_local_state(
    current: LocalCaptureState,
    target: LocalCaptureState,
) -> Optional[LocalCaptureState]:
    if current not in _LOCAL_ORDER or target not in _LOCAL_ORDER:
        return None
    current_index = _LOCAL_ORDER.index(current)
    target_index = _LOCAL_ORDER.index(target)
    if target_index <= current_index:
        return None
    return _LOCAL_ORDER[current_index + 1]


def _is_global_auth_failure(error: SyncClientError) -> bool:
    if error.code.startswith(("TD-UPLOAD-", "TD-STORAGE-")):
        return False
    return error.code.startswith("TD-AUTH-") or error.status_code in {401, 403}


def _capture_traceparent(capture_id: str, span_seed: str) -> str:
    trace_id = hashlib.sha256(capture_id.encode("utf-8")).hexdigest()[:32]
    span_id = hashlib.sha256(span_seed.encode("utf-8")).hexdigest()[:16]
    if set(trace_id) == {"0"} or set(span_id) == {"0"}:
        raise QueueIntegrityError("追踪标识不能为全零")
    return f"00-{trace_id}-{span_id}-01"
