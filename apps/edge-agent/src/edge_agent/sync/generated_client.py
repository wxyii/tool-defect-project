"""冻结 OpenAPI 生成客户端到采集端同步端口的显式适配。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Mapping, Protocol, Sequence, cast
from urllib.parse import urlsplit
from uuid import UUID

from tool_defect_contracts import (
    ApiClient,
    CONTRACT_MAJOR_VERSION,
    CONTRACT_SOURCE_SHA256,
)

from ..local_queue.models import CaptureRecord, LocalImageRecord
from .client import (
    CaptureInitialization,
    CentralCapture,
    DetectionSubmission,
    SyncClientError,
    UploadTicket,
)


class ObjectUploader(Protocol):
    """短时签名数据面的窄端口，不持有长期对象存储凭据。"""

    def put(
        self,
        *,
        url: str,
        method: str,
        headers: Mapping[str, str],
        file_path: Path,
        sha256: str,
        size_bytes: int,
    ) -> str:
        """上传并返回不透明回执，例如 ETag。"""


class GeneratedClientAdapter:
    """只调用生成包中声明的 v1 操作，不复制私有网络端点。"""

    def __init__(
        self,
        generated_client: ApiClient,
        *,
        object_uploader: ObjectUploader,
        expected_contract_sha256: str,
        clock=time.time,
    ) -> None:
        if CONTRACT_MAJOR_VERSION != 1:
            raise ValueError("采集端只兼容 v1 主版本契约")
        if expected_contract_sha256 != CONTRACT_SOURCE_SHA256:
            raise ValueError("采集端配置的契约哈希与生成包不一致")
        transport_contract_sha256 = getattr(
            generated_client,
            "contract_source_sha256",
            None,
        )
        if transport_contract_sha256 != CONTRACT_SOURCE_SHA256:
            raise ValueError("实际 HTTP 传输的契约哈希与生成包不一致")
        self.generated_client = generated_client
        self.object_uploader = object_uploader
        self.clock = clock

    def initialize_capture(
        self,
        *,
        capture: CaptureRecord,
        images: Sequence[LocalImageRecord],
        idempotency_key: str,
        request_id: str,
    ) -> CaptureInitialization:
        body = {
            "capture_id": capture.capture_id,
            "station_id": capture.station_id,
            "trigger": {
                "trigger_id": capture.trigger_id,
                "client_sequence": capture.client_sequence,
                "occurred_at": capture.occurred_at,
                "source": capture.trigger_source,
            },
            "recipe_id": capture.recipe_id,
            "quality": {
                "status": capture.quality_status,
                "warnings": list(capture.quality_warnings),
            },
            "images": [
                {
                    "client_image_id": image.image_role.lower(),
                    "image_role": image.image_role,
                    "file_name": image.relative_path.name,
                    "media_type": image.media_type,
                    "size_bytes": image.size_bytes,
                    "sha256": image.sha256,
                    "width": _required_dimension(image.width, "width"),
                    "height": _required_dimension(image.height, "height"),
                }
                for image in images
            ],
        }
        response = self.generated_client.createCapture(
            _request(
                headers={
                    "Idempotency-Key": idempotency_key,
                    "X-Request-Id": request_id,
                },
                body=body,
            )
        )
        raw_images = _list(response, "images")
        if len(raw_images) != len(images):
            raise _incompatible("创建采集响应的图片数量不一致")
        tickets = tuple(
            _parse_ticket(
                _mapping(raw),
                image.image_role,
                now=self.clock(),
            )
            for raw, image in zip(raw_images, images, strict=True)
        )
        status = _string(response, "status")
        if status != "UPLOADING":
            raise _incompatible("创建采集响应未进入 UPLOADING")
        return CaptureInitialization(
            capture_id=_string(response, "capture_id"),
            central_status=status,
            upload_tickets=tickets,
        )

    def renew_upload_ticket(
        self,
        *,
        capture_id: str,
        image: LocalImageRecord,
        idempotency_key: str,
        request_id: str,
    ) -> UploadTicket:
        if image.central_image_id is None:
            raise _incompatible("续期前缺少中心 image_id")
        response = self.generated_client.renewCaptureImageUploadTicket(
            _request(
                path={
                    "capture_id": capture_id,
                    "image_id": image.central_image_id,
                },
                headers={
                    "Idempotency-Key": idempotency_key,
                    "X-Request-Id": request_id,
                },
                body={
                    "size_bytes": image.size_bytes,
                    "sha256": image.sha256,
                },
            )
        )
        ticket = _parse_ticket(
            response,
            image.image_role,
            now=self.clock(),
        )
        if ticket.image_id != image.central_image_id:
            raise _incompatible("续期票据返回了不同的 image_id")
        return ticket

    def upload_image(
        self,
        *,
        ticket: UploadTicket,
        file_path: Path,
        sha256: str,
        size_bytes: int,
    ) -> str:
        return self.object_uploader.put(
            url=ticket.url,
            method=ticket.method,
            headers=ticket.headers,
            file_path=file_path,
            sha256=sha256,
            size_bytes=size_bytes,
        )

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
    ) -> None:
        response = self.generated_client.completeCaptureImage(
            _request(
                path={"capture_id": capture_id, "image_id": image_id},
                headers={
                    "Idempotency-Key": idempotency_key,
                    "X-Request-Id": request_id,
                },
                body={
                    "size_bytes": size_bytes,
                    "sha256": sha256,
                    "upload_receipt": upload_receipt,
                },
            )
        )
        if _string(response, "image_id") != image_id:
            raise _incompatible("图片确认响应 image_id 不一致")
        if _string(response, "state") != "AVAILABLE":
            raise _incompatible("图片确认响应未进入 AVAILABLE")
        if _string(response, "sha256") != sha256:
            raise _incompatible("图片确认响应哈希不一致")

    def submit_detection(
        self,
        *,
        capture_id: str,
        idempotency_key: str,
        request_id: str,
    ) -> DetectionSubmission:
        response = self.generated_client.submitCapture(
            _request(
                path={"capture_id": capture_id},
                headers={
                    "Idempotency-Key": idempotency_key,
                    "X-Request-Id": request_id,
                },
                body={"requested_at": _utc_timestamp(self.clock())},
            )
        )
        poll_after_ms = _integer(response, "poll_after_ms")
        if _string(response, "status") != "SUBMITTED":
            raise _incompatible("提交响应未进入 SUBMITTED")
        if not 100 <= poll_after_ms <= 60_000:
            raise _incompatible("提交响应 poll_after_ms 超出冻结契约")
        return DetectionSubmission(
            capture_id=_string(response, "capture_id"),
            detection_task_id=_string(response, "detection_task_id"),
            pipeline_version=_string(response, "pipeline_version"),
            poll_after_ms=poll_after_ms,
        )

    def get_capture(
        self,
        *,
        capture_id: str,
        request_id: str,
    ) -> CentralCapture:
        response = self.generated_client.getEdgeCapture(
            _request(
                path={"capture_id": capture_id},
                headers={"X-Request-Id": request_id},
            )
        )
        central = _parse_central_capture(response)
        if central.capture_id != capture_id:
            raise _incompatible("轮询响应 capture_id 与请求不一致")
        return central

    def reconcile_captures(
        self,
        *,
        capture_ids: Sequence[str],
        request_id: str,
    ) -> Sequence[CentralCapture]:
        response = self.generated_client.queryCaptureSync(
            _request(
                headers={
                    "Idempotency-Key": f"sync:{request_id}",
                    "X-Request-Id": request_id,
                },
                body={"capture_ids": list(capture_ids)},
            )
        )
        return tuple(
            _parse_central_capture(_mapping(item))
            for item in _list(response, "items")
        )

    def send_heartbeat(
        self,
        *,
        device_id: str,
        payload: Mapping[str, object],
        idempotency_key: str,
        request_id: str,
    ) -> None:
        response = self.generated_client.reportDeviceHeartbeat(
            _request(
                path={"device_id": device_id},
                headers={
                    "Idempotency-Key": idempotency_key,
                    "X-Request-Id": request_id,
                },
                body=dict(payload),
            )
        )
        if response.get("accepted") is not True:
            raise _incompatible("中心未接受设备心跳")
        request_id_value = _string(response, "request_id")
        try:
            UUID(request_id_value)
        except ValueError as error:
            raise _incompatible("心跳响应 request_id 不是 UUID") from error


def _request(
    *,
    path: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    body: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    request: dict[str, object] = {}
    if path is not None:
        request["path"] = dict(path)
    if headers is not None:
        request["headers"] = dict(headers)
    if body is not None:
        request["body"] = dict(body)
    return request


def _parse_ticket(
    raw: Mapping[str, object],
    image_role: str,
    *,
    now: float,
) -> UploadTicket:
    upload = _mapping(raw.get("upload"))
    raw_headers = _mapping(upload.get("headers"))
    if len(raw_headers) > 8:
        raise _incompatible("上传票据 headers 超过冻结契约上限")
    if not all(
        isinstance(key, str)
        and key
        and isinstance(value, str)
        for key, value in raw_headers.items()
    ):
        raise _incompatible("上传票据 headers 必须是字符串键值")
    headers = cast(Mapping[str, str], dict(raw_headers))
    method = _string(upload, "method")
    if method != "PUT":
        raise _incompatible("上传票据只允许 PUT")
    url = _string(upload, "url")
    parsed_url = urlsplit(url)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.netloc
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise _incompatible("上传票据必须使用无内嵌凭据的 HTTPS URL")
    expires_at = _parse_timestamp(_string(upload, "expires_at"))
    if expires_at <= now:
        raise _incompatible("中心返回了已过期的上传票据")
    return UploadTicket(
        image_id=_string(raw, "image_id"),
        image_role=image_role,
        url=url,
        method=method,
        headers=headers,
        expires_at=expires_at,
    )


def _parse_central_capture(raw: Mapping[str, object]) -> CentralCapture:
    disposition = raw.get("business_disposition")
    if disposition is not None and not isinstance(disposition, str):
        raise _incompatible("中心业务处置类型无效")
    poll_after_ms = _integer(raw, "poll_after_ms")
    if not 0 <= poll_after_ms <= 900_000:
        raise _incompatible("中心响应 poll_after_ms 超出冻结契约")
    return CentralCapture(
        capture_id=_string(raw, "capture_id"),
        capture_status=_string(raw, "capture_status"),
        business_disposition=cast(str | None, disposition),
        poll_after_ms=poll_after_ms,
        error_code=(
            str(raw["error_code"])
            if isinstance(raw.get("error_code"), str)
            else None
        ),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _incompatible("契约响应应为对象")
    return cast(Mapping[str, object], value)


def _list(raw: Mapping[str, object], name: str) -> list[object]:
    value = raw.get(name)
    if not isinstance(value, list):
        raise _incompatible(f"契约响应字段 {name} 应为数组")
    return value


def _string(raw: Mapping[str, object], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise _incompatible(f"契约响应字段 {name} 应为非空字符串")
    return value


def _integer(raw: Mapping[str, object], name: str) -> int:
    value = raw.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise _incompatible(f"契约响应字段 {name} 应为整数")
    return value


def _required_dimension(value: int | None, name: str) -> int:
    if value is None or value <= 0:
        raise _incompatible(f"本地图片缺少合法 {name}")
    return value


def _parse_timestamp(value: str) -> float:
    if not value.endswith("Z"):
        raise _incompatible("票据过期时间必须使用 UTC Z 后缀")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise _incompatible("票据过期时间格式无效") from error
    if parsed.tzinfo is None:
        raise _incompatible("票据过期时间必须包含时区")
    return parsed.timestamp()


def _utc_timestamp(epoch_seconds: float) -> str:
    return (
        datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _incompatible(message: str) -> SyncClientError:
    return SyncClientError(
        message,
        code="TD-API-INCOMPATIBLE-001",
        retryable=False,
    )
