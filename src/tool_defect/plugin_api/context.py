"""插件可见的最小只读运行上下文。"""

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Protocol


class CancellationToken(Protocol):
    def is_cancelled(self) -> bool:
        ...

    def raise_if_cancelled(self) -> None:
        ...


class NeverCancelled:
    def is_cancelled(self) -> bool:
        return False

    def raise_if_cancelled(self) -> None:
        return None


@dataclass(frozen=True)
class RuntimeContext:
    run_id: str
    attempt_id: str
    pipeline_version: str
    config_sha256: str
    code_signature: str
    runtime_slot_id: str
    device: str
    temp_dir: Path
    random_seed: int
    deadline_monotonic: float
    cancellation: CancellationToken

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "attempt_id",
            "pipeline_version",
            "config_sha256",
            "code_signature",
            "runtime_slot_id",
            "device",
        ):
            if (
                not isinstance(getattr(self, field_name), str)
                or not getattr(self, field_name)
            ):
                raise ValueError(f"运行上下文字段不能为空：{field_name}")
        if re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.config_sha256
        ) is None:
            raise ValueError("运行上下文配置哈希格式非法")
        if self.device not in {"cpu", "gpu"}:
            raise ValueError("运行上下文设备必须为 cpu 或 gpu")
        if not isinstance(self.temp_dir, Path) or not self.temp_dir.is_absolute():
            raise ValueError("插件临时目录必须是绝对路径")
        if (
            isinstance(self.random_seed, bool)
            or not isinstance(self.random_seed, int)
            or self.random_seed < 0
        ):
            raise ValueError("随机种子不能为负数")
        if not isinstance(self.deadline_monotonic, (int, float)) or not (
            math.isfinite(float(self.deadline_monotonic))
        ):
            raise ValueError("插件截止时间必须是有限数值")
        if not callable(
            getattr(self.cancellation, "is_cancelled", None)
        ) or not callable(
            getattr(self.cancellation, "raise_if_cancelled", None)
        ):
            raise TypeError("运行上下文取消令牌不符合协议")
