"""无网络副作用的结构化日志、W3C 追踪和低基数指标出口。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import re
import socket
import sys
from typing import Any, Mapping, TextIO
from urllib.parse import urlsplit, urlunsplit


_EVENT = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_TRACEPARENT = re.compile(
    r"^00-([0-9a-f]{32})-([0-9a-f]{16})-(0[01])$"
)
_METRIC = re.compile(r"^tool_defect_[a-z][a-z0-9_]*$")
_LABEL = re.compile(r"^[a-z][a-z0-9_]*$")
_ABSOLUTE_PATH = re.compile(r"^(?:/|[A-Za-z]:[\\/]|\\\\)")
_FORBIDDEN_LABELS = {
    "capture_id",
    "task_id",
    "detection_task_id",
    "attempt_id",
    "request_id",
    "trace_id",
    "span_id",
    "user_id",
    "actor_id",
    "object_key",
    "error",
    "error_message",
}
_SECRET_KEYS = {
    "authorization",
    "token",
    "access_token",
    "refresh_token",
    "cookie",
    "password",
    "secret",
    "secret_key",
    "private_key",
    "signed_url",
    "signature",
    "base64",
    "image_bytes",
}


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    sampled: bool

    @classmethod
    def parse(cls, traceparent: str) -> "TraceContext":
        match = _TRACEPARENT.fullmatch(traceparent)
        if match is None:
            raise ValueError("traceparent 不符合 W3C v00 格式")
        trace_id, span_id, flags = match.groups()
        if set(trace_id) == {"0"} or set(span_id) == {"0"}:
            raise ValueError("traceparent 不能使用全零追踪或跨度标识")
        return cls(trace_id, span_id, flags == "01")

    @property
    def traceparent(self) -> str:
        flags = "01" if self.sampled else "00"
        return f"00-{self.trace_id}-{self.span_id}-{flags}"


class JsonTelemetry:
    def __init__(
        self,
        *,
        service: str,
        service_version: str,
        environment: str,
        host: str | None = None,
        stream: TextIO | None = None,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        for value, name in (
            (service, "service"),
            (service_version, "service_version"),
            (environment, "environment"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 不能为空")
        self._base = {
            "service": service,
            "service_version": service_version,
            "environment": environment,
            "host": host or socket.gethostname(),
        }
        self._stream = stream or sys.stdout
        self._clock = clock

    def emit(
        self,
        event: str,
        message: str,
        *,
        level: str = "INFO",
        traceparent: str | None = None,
        **fields: Any,
    ) -> Mapping[str, Any]:
        if _EVENT.fullmatch(event) is None:
            raise ValueError("事件名必须使用稳定的领域.动作格式")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("日志文案不能为空")
        normalized_level = level.upper()
        if normalized_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError("日志级别不受支持")
        now = self._clock()
        if isinstance(now, (int, float)) and not isinstance(now, bool):
            now = datetime.fromtimestamp(float(now), timezone.utc)
        if not isinstance(now, datetime):
            raise TypeError("日志时钟必须返回 datetime 或时间戳")
        if now.tzinfo is None:
            raise ValueError("日志时间必须包含时区")
        payload: dict[str, Any] = {
            "timestamp": now.astimezone(timezone.utc).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z"),
            "level": normalized_level,
            **self._base,
            "event": event,
            "message": message.strip(),
        }
        if traceparent is not None:
            context = TraceContext.parse(traceparent)
            payload["trace_id"] = context.trace_id
            payload["span_id"] = context.span_id
            payload["trace_sampled"] = context.sampled
        for key, value in fields.items():
            if not isinstance(key, str) or not key:
                raise ValueError("日志字段名不能为空")
            payload[key] = _sanitize(key, value)
        line = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self._stream.write(line + "\n")
        self._stream.flush()
        return payload


class MetricRegistry:
    """只接受部署单元声明过的有限标签，不接收任务或用户标识。"""

    def __init__(self, allowed_labels: set[str]) -> None:
        if any(_LABEL.fullmatch(label) is None for label in allowed_labels):
            raise ValueError("指标标签名不合法")
        forbidden = allowed_labels & _FORBIDDEN_LABELS
        if forbidden:
            raise ValueError(f"指标标签包含高基数字段：{sorted(forbidden)}")
        self._allowed_labels = frozenset(allowed_labels)
        self._points: dict[
            tuple[str, tuple[tuple[str, str], ...]], float
        ] = {}

    def increment(
        self,
        name: str,
        amount: float = 1.0,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        key = self._key(name, labels)
        value = _finite(amount)
        if value < 0:
            raise ValueError("计数器增量不能为负数")
        self._points[key] = self._points.get(key, 0.0) + value

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        self._points[self._key(name, labels)] = _finite(value)

    def snapshot(self) -> Mapping[
        tuple[str, tuple[tuple[str, str], ...]], float
    ]:
        return dict(self._points)

    def render_prometheus(self) -> str:
        lines: list[str] = []
        for (name, labels), value in sorted(self._points.items()):
            suffix = ""
            if labels:
                body = ",".join(
                    f'{key}="{_escape_label(label)}"'
                    for key, label in labels
                )
                suffix = "{" + body + "}"
            lines.append(f"{name}{suffix} {value:g}")
        return "\n".join(lines) + ("\n" if lines else "")

    def _key(
        self,
        name: str,
        labels: Mapping[str, str] | None,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        if _METRIC.fullmatch(name) is None:
            raise ValueError("指标名必须使用 tool_defect_ 前缀")
        normalized = dict(labels or {})
        unknown = set(normalized) - self._allowed_labels
        if unknown:
            raise ValueError(f"指标包含未声明或高基数标签：{sorted(unknown)}")
        if any(
            not isinstance(value, str)
            or not value
            or len(value) > 64
            for value in normalized.values()
        ):
            raise ValueError("指标标签值必须是 1 到 64 个字符")
        return name, tuple(sorted(normalized.items()))


def _sanitize(key: str, value: Any) -> Any:
    normalized_key = key.lower()
    if normalized_key in _SECRET_KEYS or any(
        marker in normalized_key
        for marker in ("password", "private_key", "access_token")
    ):
        return "[REDACTED]"
    if isinstance(value, bytes):
        return "[BINARY_REDACTED]"
    if isinstance(value, str):
        lowered = value.lower()
        if "data:image/" in lowered:
            return "[IMAGE_CONTENT_REDACTED]"
        if normalized_key.endswith("url") or normalized_key.endswith("uri"):
            parts = urlsplit(value)
            if parts.scheme and parts.netloc:
                return urlunsplit(
                    (parts.scheme, parts.netloc, parts.path, "", "")
                )
        if (
            normalized_key.endswith("path")
            and _ABSOLUTE_PATH.match(value)
        ):
            return "[LOCAL_PATH_REDACTED]"
        return value[:2048]
    if isinstance(value, Mapping):
        return {
            str(child_key): _sanitize(str(child_key), child_value)
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(key, item) for item in value]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return _finite(value)
    return _sanitize(key, str(value))


def _finite(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("指标值必须是数字")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("指标值必须有限")
    return result


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
