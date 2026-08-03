"""第二版产线单项接口适配；第一版同步器继续独立保留。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping
from uuid import UUID

from tool_defect_contracts.v2 import (
    ApiClientV2,
    CONTRACT_MAJOR_VERSION,
    CONTRACT_SOURCE_SHA256,
)

from ..telemetry import MetricRegistry


@dataclass(frozen=True, slots=True)
class ProductionImage:
    bucket: str
    object_key: str
    sha256: str
    size_bytes: int
    media_type: str
    object_version: str | None = None

    def to_contract(self) -> dict[str, object]:
        if not self.object_key.startswith("production-originals/"):
            raise ValueError("第二版产线对象必须位于 production-originals 前缀")
        if len(self.sha256) != 64 or any(character not in "0123456789abcdef" for character in self.sha256):
            raise ValueError("第二版产线对象 SHA-256 非法")
        if self.size_bytes < 1 or self.media_type not in {"image/jpeg", "image/png"}:
            raise ValueError("第二版产线对象大小或媒体类型非法")
        value: dict[str, object] = {
            "bucket": self.bucket,
            "object_key": self.object_key,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
        }
        if self.object_version is not None:
            value["object_version"] = self.object_version
        return value


@dataclass(frozen=True, slots=True)
class ProductionItemAcceptance:
    capture_id: str
    batch_id: str
    batch_item_id: str
    detection_task_id: str
    status: str


class ProductionItemClientAdapter:
    """只通过生成的第二版操作提交单个对象引用。"""

    def __init__(self, generated_client: ApiClientV2, *, expected_contract_sha256: str,
                 metrics: MetricRegistry | None = None) -> None:
        if CONTRACT_MAJOR_VERSION != 2:
            raise ValueError("产线单项适配只兼容第二版主契约")
        if expected_contract_sha256 != CONTRACT_SOURCE_SHA256:
            raise ValueError("边缘端第二版契约哈希与生成包不一致")
        if getattr(generated_client, "contract_source_sha256", None) != CONTRACT_SOURCE_SHA256:
            raise ValueError("实际第二版 HTTP 传输契约哈希不一致")
        self._client = generated_client
        self._metrics = metrics
        self._accepted_digests: dict[str, str] = {}

    def submit(self, *, capture_id: str, image: ProductionImage,
               idempotency_key: str, request_id: str) -> ProductionItemAcceptance:
        _uuid(capture_id, "capture_id")
        if len(idempotency_key) < 8 or len(idempotency_key) > 128:
            raise ValueError("产线单项幂等键长度非法")
        body = {"capture_id": capture_id, "image": image.to_contract()}
        digest = hashlib.sha256(
            (capture_id + "\0" + image.sha256 + "\0" + image.object_key).encode("utf-8")
        ).hexdigest()
        previous = self._accepted_digests.get(capture_id)
        if previous is not None and previous != digest:
            self._count("hash_conflict")
            raise ValueError("相同 capture_id 的单图对象发生哈希冲突")
        response = self._client.createProductionDetectionItemV2({
            "headers": {
                "Idempotency-Key": idempotency_key,
                "X-Request-Id": request_id,
                "traceparent": _traceparent(capture_id, request_id),
            },
            "body": body,
        })
        acceptance = ProductionItemAcceptance(
            capture_id=_same(response, "capture_id", capture_id),
            batch_id=_uuid_field(response, "batch_id"),
            batch_item_id=_uuid_field(response, "batch_item_id"),
            detection_task_id=_uuid_field(response, "detection_task_id"),
            status=_status(response),
        )
        self._accepted_digests[capture_id] = digest
        self._count("accepted")
        return acceptance

    def _count(self, result: str) -> None:
        if self._metrics is not None:
            self._metrics.increment(
                "tool_defect_edge_contract_requests_total",
                labels={"contract_version": "v2", "result": result},
            )


def _traceparent(capture_id: str, request_id: str) -> str:
    trace = hashlib.sha256(capture_id.encode()).hexdigest()[:32]
    span = hashlib.sha256(request_id.encode()).hexdigest()[:16]
    return f"00-{trace}-{span}-01"


def _uuid(value: str, field: str) -> str:
    try:
        UUID(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} 不是 UUID") from error
    return value


def _uuid_field(response: Mapping[str, object], field: str) -> str:
    value = response.get(field)
    if not isinstance(value, str):
        raise ValueError(f"第二版响应缺少 {field}")
    return _uuid(value, field)


def _same(response: Mapping[str, object], field: str, expected: str) -> str:
    value = response.get(field)
    if value != expected:
        raise ValueError(f"第二版响应 {field} 与请求不一致")
    return expected


def _status(response: Mapping[str, object]) -> str:
    status = response.get("status")
    if status not in {"QUEUED", "PROCESSING"}:
        raise ValueError("第二版产线项响应未进入可推理状态")
    return str(status)
