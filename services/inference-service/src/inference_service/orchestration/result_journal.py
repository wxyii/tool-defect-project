"""回调状态未知时持久保存已经确定的推理结果。"""

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Protocol

from inference_service.clients.canonical_json import sha256


_SAFE_ID = re.compile(r"^[0-9a-f-]{36}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PendingResult:
    attempt_id: str
    message_id: str
    detection_task_id: str
    capture_id: str
    traceparent: str
    result_sha256: str
    payload: Mapping[str, Any]
    callback_accepted: bool = False

    def __post_init__(self) -> None:
        if _SAFE_ID.fullmatch(self.attempt_id) is None:
            raise ValueError("回调清单 attempt_id 非法")
        if _SHA256.fullmatch(self.result_sha256) is None:
            raise ValueError("回调清单结果摘要非法")
        if sha256(self.payload) != self.result_sha256:
            raise ValueError("回调清单负载摘要不匹配")
        if not isinstance(self.callback_accepted, bool):
            raise TypeError("回调接受标记必须是布尔值")


class ResultJournal(Protocol):
    def load(self, attempt_id: str) -> PendingResult | None:
        ...

    def store(self, result: PendingResult) -> None:
        ...

    def mark_accepted(self, attempt_id: str) -> None:
        ...

    def delete(self, attempt_id: str) -> None:
        ...


class FileResultJournal:
    """单文件原子替换；目录与文件都只允许当前进程用户访问。"""

    def __init__(self, root: Path, *, maximum_accepted_entries: int = 4096):
        self._root = Path(root)
        self._maximum_accepted_entries = int(maximum_accepted_entries)
        if self._maximum_accepted_entries < 1:
            raise ValueError("已接受回调清单上限必须为正数")

    def load(self, attempt_id: str) -> PendingResult | None:
        path = self._path(attempt_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        required = {
            "attempt_id",
            "message_id",
            "detection_task_id",
            "capture_id",
            "traceparent",
            "result_sha256",
            "payload",
        }
        allowed = required | {"callback_accepted"}
        if (
            not isinstance(raw, dict)
            or not required.issubset(raw)
            or set(raw).difference(allowed)
        ):
            raise ValueError("回调清单字段不完整")
        raw.setdefault("callback_accepted", False)
        return PendingResult(**raw)

    def store(self, result: PendingResult) -> None:
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._root, 0o700)
        path = self._path(result.attempt_id)
        temporary = path.with_suffix(".tmp")
        body = {
            "attempt_id": result.attempt_id,
            "message_id": result.message_id,
            "detection_task_id": result.detection_task_id,
            "capture_id": result.capture_id,
            "traceparent": result.traceparent,
            "result_sha256": result.result_sha256,
            "payload": dict(result.payload),
            "callback_accepted": result.callback_accepted,
        }
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(
                    body,
                    stream,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            _sync_directory(self._root)
        finally:
            if temporary.exists():
                temporary.unlink()
        self._prune_accepted()

    def mark_accepted(self, attempt_id: str) -> None:
        result = self.load(attempt_id)
        if result is None or result.callback_accepted:
            return
        self.store(replace(result, callback_accepted=True))

    def delete(self, attempt_id: str) -> None:
        path = self._path(attempt_id)
        if path.exists():
            path.unlink()
            _sync_directory(self._root)
        try:
            self._root.rmdir()
        except OSError:
            pass

    def _path(self, attempt_id: str) -> Path:
        if _SAFE_ID.fullmatch(attempt_id) is None:
            raise ValueError("回调清单 attempt_id 非法")
        return self._root / f"{attempt_id}.json"

    def _prune_accepted(self) -> None:
        accepted: list[Path] = []
        for path in self._root.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                isinstance(raw, dict)
                and raw.get("callback_accepted") is True
            ):
                accepted.append(path)
        accepted.sort(key=lambda path: (path.stat().st_mtime_ns, path.name))
        for path in accepted[: -self._maximum_accepted_entries]:
            path.unlink()
        if len(accepted) > self._maximum_accepted_entries:
            _sync_directory(self._root)


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
