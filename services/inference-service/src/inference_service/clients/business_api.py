"""冻结内部接口上的幂等业务后端回调客户端。"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping, Protocol

from tool_defect.plugin_api import (
    PluginErrorCode,
    PluginErrorInfo,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_TRACEPARENT = re.compile(
    r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
)
_ERROR_CODES = {
    PluginErrorCode.INPUT_INVALID: "TD-INPUT-INVALID-001",
    PluginErrorCode.PREPROCESS_REJECTED: "TD-PREPROCESS-REJECTED-001",
    PluginErrorCode.MODEL_INCOMPATIBLE: "TD-MODEL-INCOMPATIBLE-001",
    PluginErrorCode.RESOURCE_EXHAUSTED: "TD-RUNTIME-RESOURCE-001",
    PluginErrorCode.RUNTIME_TRANSIENT: "TD-RUNTIME-TRANSIENT-001",
    PluginErrorCode.PLUGIN_BUG: "TD-PLUGIN-BUG-001",
}
_STAGES = {
    "download": "DOWNLOAD",
    "decode": "DECODE",
    "preprocess": "PREPROCESS",
    "plugin_config": "PREPROCESS",
    "model_load": "MODEL_LOAD",
    "model_warmup": "MODEL_LOAD",
    "artifact_verification": "MODEL_LOAD",
    "runtime_slot": "MODEL_LOAD",
    "inference": "INFERENCE",
    "result_validation": "POSTPROCESS",
    "postprocess": "POSTPROCESS",
    "upload": "UPLOAD",
    "callback": "CALLBACK",
    "orchestration": "INFERENCE",
}


@dataclass(frozen=True)
class CallbackAcceptance:
    accepted: bool
    result_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise TypeError("后端接受标记必须是布尔值")
        if (
            not isinstance(self.result_sha256, str)
            or _SHA256.fullmatch(self.result_sha256) is None
        ):
            raise ValueError("回调结果 SHA-256 格式非法")


class InternalApiTransport(Protocol):
    """认证、双向传输层安全和超时由此注入边界负责。"""

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ...


class BusinessApiClient(Protocol):
    async def create_attempt(
        self,
        detection_task_id: str,
        message_id: str,
        worker_id: str,
        runtime_version: str,
        model_sha256: str,
        traceparent: str,
    ) -> str:
        ...

    async def put_result(
        self,
        attempt_id: str,
        payload: Mapping[str, Any],
        result_sha256: str,
        traceparent: str,
    ) -> CallbackAcceptance:
        ...

    async def put_failure(
        self,
        attempt_id: str,
        error: PluginErrorInfo,
        traceparent: str,
    ) -> CallbackAcceptance:
        ...


class StandardBusinessApiClient:
    """只组装冻结请求；不持有数据库或对象存储能力。"""

    def __init__(self, transport: InternalApiTransport):
        self._transport = transport

    async def create_attempt(
        self,
        detection_task_id: str,
        message_id: str,
        worker_id: str,
        runtime_version: str,
        model_sha256: str,
        traceparent: str,
    ) -> str:
        _require_uuid(detection_task_id, "detection_task_id")
        _require_uuid(message_id, "message_id")
        _require_traceparent(traceparent)
        digest = _require_sha256(model_sha256)
        if (
            not isinstance(worker_id, str)
            or not worker_id
            or len(worker_id) > 128
            or not isinstance(runtime_version, str)
            or not runtime_version
            or len(runtime_version) > 128
        ):
            raise ValueError("工作进程或运行时版本格式非法")
        response = await self._transport.request(
            "POST",
            (
                "/internal/v1/detection-tasks/"
                f"{detection_task_id}/attempts"
            ),
            headers=_headers(message_id, traceparent),
            payload={
                "message_id": message_id,
                "worker_id": worker_id,
                "runtime_version": runtime_version,
                "model_sha256": digest,
            },
        )
        if (
            not isinstance(response, Mapping)
            or set(response) != {"attempt_id", "attempt_no", "status"}
            or response.get("status") != "RUNNING"
            or isinstance(response.get("attempt_no"), bool)
            or not isinstance(response.get("attempt_no"), int)
            or response["attempt_no"] < 1
        ):
            raise ValueError("创建尝试响应与冻结契约不一致")
        return _require_uuid(response["attempt_id"], "attempt_id")

    async def put_result(
        self,
        attempt_id: str,
        payload: Mapping[str, Any],
        result_sha256: str,
        traceparent: str,
    ) -> CallbackAcceptance:
        _require_uuid(attempt_id, "attempt_id")
        _require_traceparent(traceparent)
        digest = _require_sha256(result_sha256)
        response = await self._transport.request(
            "PUT",
            f"/internal/v1/detection-attempts/{attempt_id}/result",
            headers=_headers(digest, traceparent),
            payload=dict(payload),
        )
        if (
            not isinstance(response, Mapping)
            or set(response) != {"accepted", "result_sha256"}
            or response.get("accepted") is not True
            or _require_sha256(response.get("result_sha256")) != digest
        ):
            raise ValueError("结果接受响应与请求哈希不一致")
        return CallbackAcceptance(True, digest)

    async def put_failure(
        self,
        attempt_id: str,
        error: PluginErrorInfo,
        traceparent: str,
    ) -> CallbackAcceptance:
        _require_uuid(attempt_id, "attempt_id")
        _require_traceparent(traceparent)
        if not isinstance(error, PluginErrorInfo):
            raise TypeError("失败回调必须使用 PluginErrorInfo")
        payload = {
            "error_code": _ERROR_CODES[error.code],
            "stage": _STAGES.get(error.stage, "INFERENCE"),
            "retryable": error.retryable,
            "message": error.safe_message[:512],
            "occurred_at": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
        }
        digest = _payload_sha256(payload)
        response = await self._transport.request(
            "PUT",
            f"/internal/v1/detection-attempts/{attempt_id}/failure",
            headers=_headers(digest, traceparent),
            payload=payload,
        )
        if (
            not isinstance(response, Mapping)
            or set(response) != {"accepted", "request_id"}
            or not isinstance(response.get("accepted"), bool)
        ):
            raise ValueError("失败接受响应与冻结契约不一致")
        _require_uuid(response["request_id"], "request_id")
        return CallbackAcceptance(response["accepted"], digest)


def _headers(idempotency_key: str, traceparent: str) -> dict[str, str]:
    return {
        "Idempotency-Key": idempotency_key,
        "traceparent": traceparent,
        "Content-Type": "application/json",
    }


def _require_uuid(value: Any, field: str) -> str:
    if not isinstance(value, str) or _UUID.fullmatch(value) is None:
        raise ValueError(f"{field} 不符合冻结 UUID 契约")
    return value


def _require_traceparent(value: Any) -> str:
    if not isinstance(value, str) or _TRACEPARENT.fullmatch(value) is None:
        raise ValueError("traceparent 格式非法")
    return value


def _require_sha256(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("SHA-256 格式非法")
    digest = value.removeprefix("sha256:")
    if _SHA256.fullmatch(digest) is None:
        raise ValueError("SHA-256 格式非法")
    return digest


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
