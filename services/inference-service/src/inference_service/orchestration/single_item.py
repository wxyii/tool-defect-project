"""第二版单图片项推理编排；与第一版多图兼容路径并行。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Protocol
from uuid import NAMESPACE_URL, uuid5

from inference_service.quality.checker import QualityResult
from inference_service.clients.canonical_json import sha256
from inference_service.orchestration.result_journal import (
    FileResultJournal,
    PendingResult,
    ResultJournal,
)
from inference_service.storage.materializer import ObjectMaterializer, ObjectReference


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_TRACEPARENT = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class SingleItemTask:
    message_id: str
    occurred_at: str
    idempotency_key: str
    traceparent: str
    batch_item_id: str
    detection_task_id: str
    image: ObjectReference
    pipeline_version: str

    @classmethod
    def from_contract(cls, payload: Mapping[str, Any]) -> "SingleItemTask":
        required = {
            "message_id", "occurred_at", "idempotency_key", "traceparent",
            "batch_item_id", "detection_task_id", "image", "pipeline_version",
        }
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise ValueError("第二版单图片项事件字段与冻结契约不一致")
        for field in ("message_id", "batch_item_id", "detection_task_id"):
            if not isinstance(payload[field], str) or _UUID.fullmatch(payload[field]) is None:
                raise ValueError(f"{field} 不符合 UUID 契约")
        if not isinstance(payload["traceparent"], str) or _TRACEPARENT.fullmatch(payload["traceparent"]) is None:
            raise ValueError("traceparent 不符合冻结契约")
        try:
            datetime.fromisoformat(str(payload["occurred_at"]).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("occurred_at 不符合时间契约") from error
        if not 8 <= len(str(payload["idempotency_key"])) <= 128:
            raise ValueError("idempotency_key 长度不符合冻结契约")
        if not 1 <= len(str(payload["pipeline_version"])) <= 100:
            raise ValueError("pipeline_version 长度不符合冻结契约")
        image = payload["image"]
        if not isinstance(image, Mapping):
            raise ValueError("image 必须为单一对象引用")
        allowed = {"bucket", "object_key", "sha256", "size_bytes", "media_type", "object_version"}
        if set(image).difference(allowed) or not allowed.difference({"object_version"}).issubset(image):
            raise ValueError("image 字段与第二版对象引用不一致")
        return cls(
            message_id=str(payload["message_id"]),
            occurred_at=str(payload["occurred_at"]),
            idempotency_key=str(payload["idempotency_key"]),
            traceparent=str(payload["traceparent"]),
            batch_item_id=str(payload["batch_item_id"]),
            detection_task_id=str(payload["detection_task_id"]),
            image=ObjectReference(
                image_id=str(payload["batch_item_id"]),
                bucket=str(image["bucket"]), object_key=str(image["object_key"]),
                sha256=str(image["sha256"]), size_bytes=image["size_bytes"],
                media_type=str(image["media_type"]), object_version=image.get("object_version"),
            ),
            pipeline_version=str(payload["pipeline_version"]),
        )


@dataclass(frozen=True, slots=True)
class AlgorithmResult:
    outcome: str
    confidence: float
    defect_regions: tuple[Mapping[str, Any], ...]
    model_version: str
    inference_ms: int

    def __post_init__(self) -> None:
        if self.outcome not in {"QUALIFIED", "UNQUALIFIED", "INCONCLUSIVE"}:
            raise ValueError("算法输出结论非法")
        if not 0.0 <= self.confidence <= 1.0 or self.inference_ms < 0 or not self.model_version:
            raise ValueError("算法输出置信度、版本或耗时非法")


class SingleImageDecoderProtocol(Protocol):
    def decode(self, materialized: Any) -> Any: ...


class ImageQualityChecker(Protocol):
    checker_version: str
    def inspect(self, pixels: Any) -> QualityResult: ...
    def decode_failure(self) -> QualityResult: ...


class SingleImageAlgorithm(Protocol):
    async def infer(self, frame: Any, pipeline_version: str) -> AlgorithmResult: ...


class ResultArtifactPublisher(Protocol):
    async def publish(self, task: SingleItemTask, result: Mapping[str, Any]) -> Mapping[str, Any]: ...


class InferenceEventPublisher(Protocol):
    async def publish_completed(self, payload: Mapping[str, Any]) -> bool: ...
    async def publish_failed(self, payload: Mapping[str, Any]) -> bool: ...


class SingleItemOrchestrator:
    def __init__(self, *, materializer: ObjectMaterializer, decoder: SingleImageDecoderProtocol,
                 quality_checker: ImageQualityChecker, algorithm: SingleImageAlgorithm,
                 artifact_publisher: ResultArtifactPublisher,
                 event_publisher: InferenceEventPublisher, temp_root: Path,
                 result_journal: ResultJournal | None = None) -> None:
        self._materializer = materializer
        self._decoder = decoder
        self._quality_checker = quality_checker
        self._algorithm = algorithm
        self._artifact_publisher = artifact_publisher
        self._event_publisher = event_publisher
        self._temp_root = Path(temp_root)
        self._temp_root.mkdir(parents=True, exist_ok=True)
        self._result_journal = result_journal or FileResultJournal(
            self._temp_root / ".single-item-journal"
        )

    async def execute(self, task: SingleItemTask) -> bool:
        attempt_id = str(uuid5(NAMESPACE_URL, "tool-defect/r4/attempt/" + task.detection_task_id))
        pending = self._result_journal.load(attempt_id)
        if pending is not None:
            if pending.callback_accepted:
                return True
            return await self._publish_pending(pending)
        try:
            with tempfile.TemporaryDirectory(prefix="single-item-", dir=self._temp_root) as name:
                materialized = await self._materializer.materialize(task.image, Path(name))
                frame = self._decoder.decode(materialized)
                quality = self._quality_checker.inspect(frame.pixels)
                algorithm = None
                if quality.overall != "REJECTED":
                    algorithm = await self._algorithm.infer(frame, task.pipeline_version)
                evidence: dict[str, Any] = {
                    "schema_version": "2.0.0",
                    "batch_item_id": task.batch_item_id,
                    "detection_task_id": task.detection_task_id,
                    "attempt_id": attempt_id,
                    "pipeline_version": task.pipeline_version,
                    "quality": quality.to_contract(),
                }
                if algorithm is None:
                    evidence.update({
                        "algorithm_outcome": "INCONCLUSIVE",
                        "quality_rejected": True,
                    })
                    outcome = "INCONCLUSIVE"
                else:
                    evidence.update({
                        "algorithm_outcome": algorithm.outcome,
                        "confidence": algorithm.confidence,
                        "defect_regions": list(algorithm.defect_regions),
                        "defect_region_count": len(algorithm.defect_regions),
                        "model_version": algorithm.model_version,
                        "inference_ms": algorithm.inference_ms,
                    })
                    outcome = algorithm.outcome
                reference = _reference(await self._artifact_publisher.publish(task, evidence))
                payload = self._base(task, attempt_id, "completed")
                payload.update({
                    "quality": quality.to_contract(),
                    "algorithm_outcome": outcome,
                    "result_reference": reference,
                })
                return await self._record_and_publish(task, attempt_id, payload)
        except Exception as error:
            payload = self._base(task, attempt_id, "failed")
            payload.update({
                "error_code": _safe_error_code(error),
                "retryable": not isinstance(error, (ValueError, TypeError)),
                "safe_detail": "单图推理未形成可接受结果",
            })
            return await self._record_and_publish(task, attempt_id, payload)

    async def _record_and_publish(
        self,
        task: SingleItemTask,
        attempt_id: str,
        payload: Mapping[str, Any],
    ) -> bool:
        pending = PendingResult(
            attempt_id=attempt_id,
            message_id=str(payload["message_id"]),
            detection_task_id=task.detection_task_id,
            capture_id=task.batch_item_id,
            traceparent=task.traceparent,
            result_sha256=sha256(payload),
            payload=dict(payload),
        )
        self._result_journal.store(pending)
        return await self._publish_pending(pending)

    async def _publish_pending(self, pending: PendingResult) -> bool:
        payload = pending.payload
        if "error_code" in payload:
            accepted = await self._event_publisher.publish_failed(payload)
        else:
            accepted = await self._event_publisher.publish_completed(payload)
        if accepted:
            self._result_journal.mark_accepted(pending.attempt_id)
        return accepted

    @staticmethod
    def _base(task: SingleItemTask, attempt_id: str, suffix: str) -> dict[str, Any]:
        return {
            "message_id": str(uuid5(NAMESPACE_URL, f"tool-defect/r4/{suffix}/" + attempt_id)),
            "occurred_at": task.occurred_at,
            "idempotency_key": f"r4-{suffix}-{task.idempotency_key}"[:128],
            "traceparent": task.traceparent,
            "batch_item_id": task.batch_item_id,
            "detection_task_id": task.detection_task_id,
            "attempt_id": attempt_id,
        }


def _reference(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"bucket", "object_key", "sha256", "size_bytes", "media_type"}
    if not isinstance(value, Mapping) or not required.issubset(value):
        raise ValueError("结果对象引用不完整")
    result = {key: value[key] for key in required}
    if "object_version" in value:
        result["object_version"] = value["object_version"]
    if not isinstance(result["sha256"], str) or _SHA256.fullmatch(result["sha256"]) is None:
        raise ValueError("结果对象 SHA-256 非法")
    return result


def _safe_error_code(error: Exception) -> str:
    name = type(error).__name__.upper()
    if "DECODE" in name:
        return "TD-IMAGE-DECODE-FAILED"
    if isinstance(error, (ValueError, TypeError)):
        return "TD-INFERENCE-OUTPUT-INVALID"
    return "TD-INFERENCE-TECHNICAL-FAILED"
