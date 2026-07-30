"""本地同步投影的数据类型和状态约束。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class LocalCaptureState(str, Enum):
    """只描述采集端同步进度，不是中央业务事实。"""

    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    SUBMITTED = "SUBMITTED"
    WAIT_RESULT = "WAIT_RESULT"
    DONE = "DONE"
    RETRY_WAIT = "RETRY_WAIT"
    LOCAL_DEAD = "LOCAL_DEAD"


_FORWARD_TRANSITIONS = {
    LocalCaptureState.PENDING: {
        LocalCaptureState.UPLOADING,
        LocalCaptureState.RETRY_WAIT,
        LocalCaptureState.LOCAL_DEAD,
    },
    LocalCaptureState.UPLOADING: {
        LocalCaptureState.UPLOADED,
        LocalCaptureState.RETRY_WAIT,
        LocalCaptureState.LOCAL_DEAD,
    },
    LocalCaptureState.UPLOADED: {
        LocalCaptureState.SUBMITTED,
        LocalCaptureState.RETRY_WAIT,
        LocalCaptureState.LOCAL_DEAD,
    },
    LocalCaptureState.SUBMITTED: {
        LocalCaptureState.WAIT_RESULT,
        LocalCaptureState.RETRY_WAIT,
        LocalCaptureState.LOCAL_DEAD,
    },
    LocalCaptureState.WAIT_RESULT: {
        LocalCaptureState.DONE,
        LocalCaptureState.RETRY_WAIT,
        LocalCaptureState.LOCAL_DEAD,
    },
    LocalCaptureState.RETRY_WAIT: {
        LocalCaptureState.PENDING,
        LocalCaptureState.UPLOADING,
        LocalCaptureState.UPLOADED,
        LocalCaptureState.SUBMITTED,
        LocalCaptureState.WAIT_RESULT,
        LocalCaptureState.LOCAL_DEAD,
    },
    LocalCaptureState.DONE: set(),
    LocalCaptureState.LOCAL_DEAD: set(),
}


def can_transition(
    current: LocalCaptureState,
    target: LocalCaptureState,
    *,
    retry_resume_state: Optional[LocalCaptureState] = None,
) -> bool:
    """判断本地投影是否可以向前推进。

    `RETRY_WAIT` 只能回到进入重试前保存的状态，避免借重试回退投影。
    """

    if current == target:
        return True
    if current is LocalCaptureState.RETRY_WAIT and retry_resume_state is not None:
        return target is retry_resume_state
    return target in _FORWARD_TRANSITIONS[current]


@dataclass(frozen=True)
class CaptureRecord:
    capture_id: str
    station_id: str
    recipe_id: str
    client_sequence: int
    trigger_id: str
    trigger_source: str
    occurred_at: str
    quality_status: str
    quality_warnings: tuple[str, ...]
    state: LocalCaptureState
    manifest_path: Path
    retry_count: int
    retry_at: Optional[float]
    resume_state: Optional[LocalCaptureState]
    next_poll_at: Optional[float]
    central_status: Optional[str]
    error_code: Optional[str]
    created_at: float
    updated_at: float
    confirmed_at: Optional[float]


@dataclass(frozen=True)
class LocalImageRecord:
    capture_id: str
    image_role: str
    relative_path: Path
    sha256: str
    size_bytes: int
    width: Optional[int]
    height: Optional[int]
    media_type: str
    upload_status: str
    central_image_id: Optional[str]
    upload_receipt: Optional[str] = None
