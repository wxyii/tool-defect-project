"""边缘端 v1 JSON API 与签名对象上传的标准库传输实现。

本模块只实现采集端会使用的七个生成客户端 operationId。TLS 证书、
Bearer 令牌和签名 URL 均由调用方注入；错误信息不会包含令牌或签名 URL。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from email.utils import parsedate_to_datetime
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import ssl
import time
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    Request,
    build_opener,
)

from tool_defect_contracts import CONTRACT_SOURCE_SHA256

from .client import SyncClientError


JsonObject = Mapping[str, object]
TokenProvider = Callable[[], str]
UrlOpener = Callable[..., object]

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_ERROR_CODE = re.compile(r"^TD-[A-Z]+-[A-Z]+-[0-9]{3}$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CONTROL_RECEIPT_HEADER = "x-tool-defect-upload-receipt"

_OPERATIONS: Mapping[str, tuple[str, str]] = {
    "createCapture": ("POST", "/api/v1/edge/captures"),
    "renewCaptureImageUploadTicket": (
        "POST",
        "/api/v1/edge/captures/{capture_id}/images/{image_id}/upload-ticket",
    ),
    "completeCaptureImage": (
        "POST",
        "/api/v1/edge/captures/{capture_id}/images/{image_id}/complete",
    ),
    "submitCapture": ("POST", "/api/v1/edge/captures/{capture_id}/submit"),
    "getEdgeCapture": ("GET", "/api/v1/edge/captures/{capture_id}"),
    "queryCaptureSync": ("POST", "/api/v1/edge/sync/captures/query"),
    "reportDeviceHeartbeat": (
        "POST",
        "/api/v1/edge/devices/{device_id}/heartbeat",
    ),
}


class _RejectRedirects(HTTPRedirectHandler):
    """拒绝重定向，避免 Bearer 令牌或签名请求被转发到其他主机。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _HttpsTransport:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        ssl_context: ssl.SSLContext | None,
        opener: UrlOpener | None,
        clock: Callable[[], float],
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("HTTP 超时必须是有限正数")
        self.timeout_seconds = float(timeout_seconds)
        if ssl_context is not None and not isinstance(ssl_context, ssl.SSLContext):
            raise TypeError("ssl_context 必须是 SSLContext")
        self.ssl_context = ssl_context or ssl.create_default_context()
        self.clock = clock
        if opener is None:
            director = build_opener(
                _RejectRedirects(),
                HTTPSHandler(context=self.ssl_context),
            )
            self._opener: UrlOpener = director.open
        else:
            resolved_opener = (
                opener if callable(opener) else getattr(opener, "open", None)
            )
            if not callable(resolved_opener):
                raise TypeError("opener 必须可调用或提供 open 方法")
            self._opener = resolved_opener

    def _open(self, request: Request) -> object:
        return self._opener(request, timeout=self.timeout_seconds)

    def _perform(self, request: Request) -> tuple[object, int]:
        try:
            response = self._open(request)
        except HTTPError as error:
            try:
                body = _read_limited(error)
                headers = error.headers
            finally:
                error.close()
            raise _status_error(
                error.code,
                headers,
                body,
                clock=self.clock,
            ) from None
        except ssl.SSLCertVerificationError:
            raise SyncClientError(
                "TLS 身份校验失败",
                code="TD-AUTH-MTLS-001",
                retryable=False,
            ) from None
        except ssl.SSLError:
            raise SyncClientError(
                "TLS 安全连接失败",
                code="TD-AUTH-MTLS-001",
                retryable=False,
            ) from None
        except URLError as error:
            if isinstance(error.reason, ssl.SSLError):
                raise SyncClientError(
                    "TLS 身份校验失败",
                    code="TD-AUTH-MTLS-001",
                    retryable=False,
                ) from None
            raise SyncClientError(
                "中心网络连接失败",
                code="TD-API-TRANSIENT-001",
                retryable=True,
            ) from None
        except TimeoutError:
            raise SyncClientError(
                "中心网络请求超时",
                code="TD-API-TIMEOUT-001",
                retryable=True,
            ) from None
        except OSError:
            raise SyncClientError(
                "中心网络连接失败",
                code="TD-API-TRANSIENT-001",
                retryable=True,
            ) from None

        status = _response_status(response)
        if not 200 <= status < 300:
            try:
                body = _read_limited(response)
                headers = getattr(response, "headers", {})
            finally:
                _close(response)
            raise _status_error(status, headers, body, clock=self.clock)
        return response, status


class HttpApiClient(_HttpsTransport):
    """与生成 ``ApiClient`` 调用形态一致的边缘端 JSON HTTP 客户端。"""

    contract_source_sha256 = CONTRACT_SOURCE_SHA256

    def __init__(
        self,
        base_url: str,
        *,
        token_provider: TokenProvider,
        ssl_context: ssl.SSLContext | None = None,
        timeout_seconds: float = 15.0,
        opener: UrlOpener | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(
            timeout_seconds=timeout_seconds,
            ssl_context=ssl_context,
            opener=opener,
            clock=clock,
        )
        if not callable(token_provider):
            raise TypeError("token_provider 必须可调用")
        self.base_url = _validate_https_url(base_url, allow_query=False)
        self.token_provider = token_provider

    def createCapture(self, request: JsonObject | None = None) -> JsonObject:
        return self._invoke("createCapture", request)

    def renewCaptureImageUploadTicket(
        self,
        request: JsonObject | None = None,
    ) -> JsonObject:
        return self._invoke("renewCaptureImageUploadTicket", request)

    def completeCaptureImage(
        self,
        request: JsonObject | None = None,
    ) -> JsonObject:
        return self._invoke("completeCaptureImage", request)

    def submitCapture(self, request: JsonObject | None = None) -> JsonObject:
        return self._invoke("submitCapture", request)

    def getEdgeCapture(self, request: JsonObject | None = None) -> JsonObject:
        return self._invoke("getEdgeCapture", request)

    def queryCaptureSync(self, request: JsonObject | None = None) -> JsonObject:
        return self._invoke("queryCaptureSync", request)

    def reportDeviceHeartbeat(
        self,
        request: JsonObject | None = None,
    ) -> JsonObject:
        return self._invoke("reportDeviceHeartbeat", request)

    def _invoke(
        self,
        operation_id: str,
        request: JsonObject | None,
    ) -> JsonObject:
        method, path_template = _OPERATIONS[operation_id]
        raw_request = _request_mapping(request)
        path_values = _nested_mapping(raw_request, "path")
        path = _render_path(path_template, path_values)
        headers = _headers(_nested_mapping(raw_request, "headers"))
        if any(name.lower() == "authorization" for name in headers):
            raise ValueError("Authorization 只能由 token_provider 提供")

        try:
            token = self.token_provider()
        except Exception:
            raise SyncClientError(
                "无法取得设备访问令牌",
                code="TD-AUTH-TOKEN-001",
                retryable=True,
            ) from None
        if (
            not isinstance(token, str)
            or not token
            or token != token.strip()
            or "\r" in token
            or "\n" in token
        ):
            raise SyncClientError(
                "设备访问令牌无效",
                code="TD-AUTH-TOKEN-001",
                retryable=False,
            )

        body: bytes | None = None
        if method == "POST":
            raw_body = raw_request.get("body")
            if not isinstance(raw_body, Mapping):
                raise ValueError(f"{operation_id} 缺少 JSON 对象 body")
            try:
                body = json.dumps(
                    dict(raw_body),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError):
                raise SyncClientError(
                    "请求正文不能编码为契约 JSON",
                    code="TD-API-INCOMPATIBLE-001",
                    retryable=False,
                ) from None
            headers.setdefault("Content-Type", "application/json")
            headers["Content-Length"] = str(len(body))
        elif "body" in raw_request:
            raise ValueError(f"{operation_id} 不接受请求 body")

        headers.setdefault("Accept", "application/json")
        headers["Authorization"] = f"Bearer {token}"
        http_request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        response, _ = self._perform(http_request)
        try:
            payload = _read_limited(response)
        finally:
            _close(response)
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SyncClientError(
                "中心响应不是有效 JSON",
                code="TD-API-INCOMPATIBLE-001",
                retryable=False,
            ) from None
        if not isinstance(decoded, dict):
            raise SyncClientError(
                "中心响应不是 JSON 对象",
                code="TD-API-INCOMPATIBLE-001",
                retryable=False,
            )
        return cast(JsonObject, decoded)


class HttpsObjectUploader(_HttpsTransport):
    """以 HTTPS PUT 流式上传签名对象并返回服务端持久化回执。"""

    def __init__(
        self,
        *,
        ssl_context: ssl.SSLContext | None = None,
        timeout_seconds: float = 60.0,
        chunk_size: int = 1024 * 1024,
        opener: UrlOpener | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(
            timeout_seconds=timeout_seconds,
            ssl_context=ssl_context,
            opener=opener,
            clock=clock,
        )
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int):
            raise ValueError("上传分块大小必须是整数")
        if chunk_size <= 0:
            raise ValueError("上传分块大小必须为正数")
        self.chunk_size = chunk_size

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
        try:
            safe_url = _validate_https_url(url, allow_query=True)
        except ValueError:
            raise SyncClientError(
                "签名对象上传地址无效",
                code="TD-UPLOAD-URL-001",
                retryable=False,
            ) from None
        if method != "PUT":
            raise SyncClientError(
                "签名对象上传只允许 PUT",
                code="TD-UPLOAD-METHOD-001",
                retryable=False,
            )
        if (
            not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes < 0
        ):
            raise SyncClientError(
                "对象大小约束无效",
                code="TD-EDGE-INTEGRITY-001",
                retryable=False,
            )
        if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
            raise SyncClientError(
                "对象 SHA-256 约束无效",
                code="TD-EDGE-INTEGRITY-001",
                retryable=False,
            )
        path = Path(file_path)
        _verify_file(path, expected_size=size_bytes, expected_sha256=sha256)

        ticket_headers = _headers(headers)
        control_receipts = [
            value
            for name, value in ticket_headers.items()
            if name.lower() == _CONTROL_RECEIPT_HEADER
        ]
        if len(control_receipts) > 1:
            raise SyncClientError(
                "签名票据包含重复的控制面上传回执",
                code="TD-UPLOAD-RECEIPT-001",
                retryable=False,
            )
        control_receipt = control_receipts[0].strip() if control_receipts else None
        if control_receipt == "":
            raise SyncClientError(
                "签名票据的控制面上传回执为空",
                code="TD-UPLOAD-RECEIPT-001",
                retryable=False,
            )
        request_headers = {
            name: value
            for name, value in ticket_headers.items()
            if name.lower() != _CONTROL_RECEIPT_HEADER
        }
        for name in request_headers:
            if name.lower() in {"host", "content-length", "transfer-encoding"}:
                raise SyncClientError(
                    "签名上传头包含禁止覆盖的传输字段",
                    code="TD-UPLOAD-HEADER-001",
                    retryable=False,
                )
        request_headers["Content-Length"] = str(size_bytes)
        body = _VerifiedFileBody(
            path,
            chunk_size=self.chunk_size,
            expected_size=size_bytes,
            expected_sha256=sha256,
        )
        upload_request = Request(
            safe_url,
            data=body,
            headers=request_headers,
            method="PUT",
        )
        response, _ = self._perform(upload_request)
        try:
            body.ensure_complete()
            response_headers = getattr(response, "headers", {})
            receipt = control_receipt or (
                _header(response_headers, "ETag")
                or _header(response_headers, "X-Upload-Receipt")
            )
        finally:
            _close(response)
        if receipt is None or not receipt.strip():
            raise SyncClientError(
                "对象存储响应缺少 ETag 或上传回执",
                code="TD-UPLOAD-RECEIPT-001",
                retryable=False,
            )
        return receipt.strip()


class _VerifiedFileBody(Iterable[bytes]):
    def __init__(
        self,
        path: Path,
        *,
        chunk_size: int,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        self.path = path
        self.chunk_size = chunk_size
        self.expected_size = expected_size
        self.expected_sha256 = expected_sha256
        self._complete = False

    def __iter__(self):
        digest = hashlib.sha256()
        actual_size = 0
        try:
            with self.path.open("rb") as stream:
                while True:
                    chunk = stream.read(self.chunk_size)
                    if not chunk:
                        break
                    actual_size += len(chunk)
                    digest.update(chunk)
                    yield chunk
        except OSError:
            raise SyncClientError(
                "流式读取本地对象失败",
                code="TD-EDGE-FILE-001",
                retryable=False,
            ) from None
        if actual_size != self.expected_size or not hmac.compare_digest(
            digest.hexdigest(),
            self.expected_sha256,
        ):
            raise SyncClientError(
                "流式上传期间本地对象发生变化",
                code="TD-EDGE-INTEGRITY-001",
                retryable=False,
            )
        self._complete = True

    def ensure_complete(self) -> None:
        if not self._complete:
            raise SyncClientError(
                "对象上传器未完整读取本地文件",
                code="TD-UPLOAD-INCOMPLETE-001",
                retryable=True,
            )


def _verify_file(
    path: Path,
    *,
    expected_size: int,
    expected_sha256: str,
) -> None:
    digest = hashlib.sha256()
    actual_size = 0
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                actual_size += len(chunk)
                digest.update(chunk)
    except OSError:
        raise SyncClientError(
            "无法读取待上传的本地对象",
            code="TD-EDGE-FILE-001",
            retryable=False,
        ) from None
    if actual_size != expected_size or not hmac.compare_digest(
        digest.hexdigest(),
        expected_sha256,
    ):
        raise SyncClientError(
            "本地对象大小或 SHA-256 不匹配",
            code="TD-EDGE-INTEGRITY-001",
            retryable=False,
        )


def _validate_https_url(url: str, *, allow_query: bool) -> str:
    if not isinstance(url, str) or not url:
        raise ValueError("URL 必须是非空字符串")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise ValueError("URL 格式无效") from error
    if parsed.scheme != "https" or parsed.hostname is None:
        raise ValueError("URL 必须使用 HTTPS 并包含主机名")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL 不得包含用户凭据")
    if parsed.fragment:
        raise ValueError("URL 不得包含片段")
    if not allow_query and parsed.query:
        raise ValueError("API base_url 不得包含查询参数")
    if not allow_query and parsed.path not in {"", "/"}:
        normalized_path = parsed.path.rstrip("/")
    else:
        normalized_path = parsed.path.rstrip("/") if not allow_query else parsed.path
    netloc = parsed.hostname
    if ":" in netloc and not netloc.startswith("["):
        netloc = f"[{netloc}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit(
        (parsed.scheme, netloc, normalized_path, parsed.query, "")
    )


def _request_mapping(request: JsonObject | None) -> Mapping[str, object]:
    if request is None:
        return {}
    if not isinstance(request, Mapping):
        raise TypeError("生成客户端 request 必须是对象")
    allowed = {"path", "headers", "body"}
    unknown = set(request) - allowed
    if unknown:
        raise ValueError(f"request 包含未知字段：{', '.join(sorted(unknown))}")
    return request


def _nested_mapping(
    request: Mapping[str, object],
    name: str,
) -> Mapping[str, object]:
    value = request.get(name, {})
    if not isinstance(value, Mapping):
        raise TypeError(f"request.{name} 必须是对象")
    return value


def _render_path(template: str, values: Mapping[str, object]) -> str:
    required = set(re.findall(r"{([a-z_]+)}", template))
    if set(values) != required:
        missing = required - set(values)
        extra = set(values) - required
        reasons = []
        if missing:
            reasons.append(f"缺少 {', '.join(sorted(missing))}")
        if extra:
            reasons.append(f"多出 {', '.join(sorted(extra))}")
        raise ValueError(f"路径参数不匹配：{'；'.join(reasons)}")
    rendered = template
    for name in sorted(required):
        value = values[name]
        if not isinstance(value, str) or not value:
            raise ValueError(f"路径参数 {name} 必须是非空字符串")
        rendered = rendered.replace(f"{{{name}}}", quote(value, safe=""))
    return rendered


def _headers(raw: Mapping[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_name, raw_value in raw.items():
        if not isinstance(raw_name, str) or not _HEADER_NAME.fullmatch(raw_name):
            raise ValueError("HTTP 头名称无效")
        if not isinstance(raw_value, str):
            raise TypeError(f"HTTP 头 {raw_name} 的值必须是字符串")
        if "\r" in raw_value or "\n" in raw_value:
            raise ValueError(f"HTTP 头 {raw_name} 包含非法换行")
        result[raw_name] = raw_value
    return result


def _response_status(response: object) -> int:
    status = getattr(response, "status", None)
    if status is None:
        getcode = getattr(response, "getcode", None)
        status = getcode() if callable(getcode) else None
    if not isinstance(status, int) or isinstance(status, bool):
        _close(response)
        raise SyncClientError(
            "HTTP 响应缺少有效状态码",
            code="TD-API-INCOMPATIBLE-001",
            retryable=False,
        )
    return status


def _read_limited(stream: object) -> bytes:
    reader = getattr(stream, "read", None)
    if not callable(reader):
        return b""
    payload = reader(_MAX_RESPONSE_BYTES + 1)
    if not isinstance(payload, bytes):
        raise SyncClientError(
            "HTTP 响应正文不是字节流",
            code="TD-API-INCOMPATIBLE-001",
            retryable=False,
        )
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise SyncClientError(
            "HTTP 响应正文超过安全上限",
            code="TD-API-INCOMPATIBLE-001",
            retryable=False,
        )
    return payload


def _close(response: object) -> None:
    closer = getattr(response, "close", None)
    if callable(closer):
        closer()


def _header(headers: object, name: str) -> str | None:
    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(name)
        if isinstance(value, str):
            return value
    if isinstance(headers, Mapping):
        for key, value in headers.items():
            if str(key).lower() == name.lower() and isinstance(value, str):
                return value
    return None


def _status_error(
    status: int,
    headers: object,
    body: bytes,
    *,
    clock: Callable[[], float],
) -> SyncClientError:
    response_code: str | None = None
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        decoded = None
    if isinstance(decoded, dict):
        candidate = decoded.get("code")
        if isinstance(candidate, str) and _ERROR_CODE.fullmatch(candidate):
            response_code = candidate

    retryable = status in {408, 425, 429} or 500 <= status <= 599
    fallback_codes = {
        400: "TD-API-VALIDATION-001",
        401: "TD-AUTH-UNAUTHORIZED-001",
        403: "TD-AUTH-FORBIDDEN-001",
        404: "TD-API-NOTFOUND-001",
        409: "TD-API-CONFLICT-001",
        422: "TD-API-VALIDATION-001",
        429: "TD-API-TRANSIENT-429",
        503: "TD-API-TRANSIENT-503",
    }
    if status in {401, 403, 409, 422}:
        retryable = False
    code = response_code or fallback_codes.get(
        status,
        (
            f"TD-API-TRANSIENT-{status:03d}"
            if retryable and 100 <= status <= 999
            else "TD-API-HTTP-001"
        ),
    )
    retry_after = _retry_after_seconds(
        _header(headers, "Retry-After"),
        now=clock(),
    )
    return SyncClientError(
        f"HTTP 请求失败，状态码 {status}",
        code=code,
        status_code=status,
        retryable=retryable,
        retry_after_seconds=retry_after if retryable else None,
    )


def _retry_after_seconds(value: str | None, *, now: float) -> float | None:
    if value is None:
        return None
    candidate = value.strip()
    if candidate.isdigit():
        return float(candidate)
    try:
        parsed = parsedate_to_datetime(candidate)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return None
    return max(0.0, parsed.timestamp() - now)


# 兼容直观命名，调用方可以任选其一而不复制传输实现。
JsonHttpApiClient = HttpApiClient
SignedPutObjectUploader = HttpsObjectUploader


__all__ = [
    "HttpApiClient",
    "HttpsObjectUploader",
    "JsonHttpApiClient",
    "SignedPutObjectUploader",
]
