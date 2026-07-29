"""插件生命周期状态机和异常分类边界。"""

from typing import Any, Mapping

from tool_defect.models.package import VerifiedModelPackage
from tool_defect.plugin_api import (
    PluginError,
    PluginErrorCode,
    PluginState,
    classify_unexpected,
)


class PreprocessorLifecycleController:
    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.state = PluginState.DISCOVERED

    def validate_config(self, config: Mapping[str, Any]) -> None:
        self._require(PluginState.DISCOVERED)
        try:
            self.plugin.validate_config(config)
        except Exception as error:
            self.state = PluginState.FAILED
            if isinstance(error, PluginError):
                raise
            raise PluginError.create(
                PluginErrorCode.INPUT_INVALID,
                "plugin_config",
                "预处理插件配置非法",
                {"exception_type": type(error).__name__},
            ) from error
        self.state = PluginState.READY

    def close(self) -> None:
        if self.state == PluginState.CLOSED:
            return
        self.state = PluginState.DRAINING
        try:
            self.plugin.close()
        finally:
            self.state = PluginState.CLOSED

    def _require(self, expected: PluginState) -> None:
        if self.state != expected:
            raise RuntimeError(
                f"预处理插件生命周期错误：{self.state.value}，"
                f"期望 {expected.value}"
            )


class AlgorithmLifecycleController:
    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.state = PluginState.DISCOVERED

    def mark_config_validated(self) -> None:
        self._transition(PluginState.DISCOVERED, PluginState.CONFIG_VALIDATED)

    def load(
        self,
        package: VerifiedModelPackage,
        context: Any,
    ) -> None:
        self._transition(
            PluginState.CONFIG_VALIDATED,
            PluginState.ARTIFACT_VERIFIED,
        )
        try:
            self.plugin.load(package, context)
        except Exception as error:
            self.state = PluginState.FAILED
            if isinstance(error, PluginError):
                raise
            raise classify_unexpected(error, "model_load") from error
        self.state = PluginState.LOADED

    def warmup(self) -> None:
        self._require(PluginState.LOADED)
        try:
            self.plugin.warmup()
        except Exception as error:
            self.state = PluginState.FAILED
            if isinstance(error, PluginError):
                raise
            raise classify_unexpected(error, "model_warmup") from error
        self.state = PluginState.WARMED
        self.state = PluginState.READY

    def drain(self) -> None:
        if self.state == PluginState.READY:
            self.state = PluginState.DRAINING

    def close(self) -> None:
        if self.state == PluginState.CLOSED:
            return
        if self.state != PluginState.DRAINING:
            self.state = PluginState.DRAINING
        try:
            self.plugin.close()
        finally:
            self.state = PluginState.CLOSED

    def _transition(
        self,
        expected: PluginState,
        target: PluginState,
    ) -> None:
        self._require(expected)
        self.state = target

    def _require(self, expected: PluginState) -> None:
        if self.state != expected:
            raise RuntimeError(
                f"算法插件生命周期错误：{self.state.value}，"
                f"期望 {expected.value}"
            )
