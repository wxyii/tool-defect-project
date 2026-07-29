"""插件异常的安全、稳定分类。"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from tool_defect.plugin_api.enums import PluginErrorCode


_RETRYABLE = {
    PluginErrorCode.INPUT_INVALID: False,
    PluginErrorCode.PREPROCESS_REJECTED: False,
    PluginErrorCode.MODEL_INCOMPATIBLE: False,
    PluginErrorCode.RESOURCE_EXHAUSTED: True,
    PluginErrorCode.RUNTIME_TRANSIENT: True,
    PluginErrorCode.PLUGIN_BUG: True,
}


@dataclass(frozen=True)
class PluginErrorInfo:
    code: PluginErrorCode
    stage: str
    safe_message: str
    details: Mapping[str, Any]

    @property
    def retryable(self) -> bool:
        return _RETRYABLE[self.code]

    def to_mapping(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "stage": self.stage,
            "message": self.safe_message,
            "retryable": self.retryable,
            "details": dict(self.details),
        }


class PluginError(RuntimeError):
    def __init__(self, info: PluginErrorInfo):
        super().__init__(info.safe_message)
        self.info = info

    @classmethod
    def create(
        cls,
        code: PluginErrorCode,
        stage: str,
        safe_message: str,
        details: Mapping[str, Any] | None = None,
    ) -> "PluginError":
        return cls(
            PluginErrorInfo(
                code=code,
                stage=stage,
                safe_message=safe_message,
                details=MappingProxyType(dict(details or {})),
            )
        )


def classify_unexpected(error: Exception, stage: str) -> PluginError:
    if isinstance(error, PluginError):
        return error
    if isinstance(error, MemoryError):
        return PluginError.create(
            PluginErrorCode.RESOURCE_EXHAUSTED,
            stage,
            "运行资源不足",
            {"exception_type": type(error).__name__},
        )
    if isinstance(error, OSError):
        return PluginError.create(
            PluginErrorCode.RUNTIME_TRANSIENT,
            stage,
            "运行时文件操作暂时失败",
            {"exception_type": type(error).__name__},
        )
    return PluginError.create(
        PluginErrorCode.PLUGIN_BUG,
        stage,
        "插件发生未分类异常",
        {"exception_type": type(error).__name__},
    )
