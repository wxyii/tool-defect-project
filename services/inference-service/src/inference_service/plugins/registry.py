"""按精确版本管理插件，禁止生产范围匹配。"""

from typing import Any

from tool_defect.plugin_api import (
    ApiVersion,
    PluginDescriptor,
    PluginError,
    PluginErrorCode,
    require_api_compatible,
)


class PluginRegistry:
    def __init__(self, host_api_version: ApiVersion):
        self._host_api_version = host_api_version
        self._plugins: dict[tuple[str, str], Any] = {}

    def register(self, plugin: Any) -> None:
        descriptor = _descriptor(plugin)
        require_api_compatible(descriptor, self._host_api_version)
        key = (descriptor.plugin_id, descriptor.plugin_version)
        if key in self._plugins:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "plugin_discovery",
                "插件精确版本重复注册",
                {
                    "plugin_id": descriptor.plugin_id,
                    "plugin_version": descriptor.plugin_version,
                },
            )
        self._plugins[key] = plugin

    def resolve(self, plugin_id: str, plugin_version: str) -> Any:
        key = (plugin_id, plugin_version)
        try:
            return self._plugins[key]
        except KeyError as error:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "plugin_discovery",
                "未登记精确插件版本",
                {
                    "plugin_id": plugin_id,
                    "plugin_version": plugin_version,
                },
            ) from error

    def descriptors(self) -> tuple[PluginDescriptor, ...]:
        return tuple(
            sorted(
                (_descriptor(plugin) for plugin in self._plugins.values()),
                key=lambda item: (item.plugin_id, item.plugin_version),
            )
        )


def _descriptor(plugin: Any) -> PluginDescriptor:
    descriptor = getattr(plugin, "descriptor", None)
    if not isinstance(descriptor, PluginDescriptor):
        raise TypeError("插件 descriptor 必须是 PluginDescriptor")
    return descriptor
