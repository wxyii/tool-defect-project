"""插件描述符、协议版本与确定性配置哈希。"""

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping

from tool_defect.plugin_api.enums import PluginErrorCode, PluginKind
from tool_defect.plugin_api.errors import PluginError


_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_PLUGIN_ID = re.compile(r"^tool-defect\.[a-z0-9][a-z0-9.-]*$")


@dataclass(frozen=True, order=True)
class ApiVersion:
    major: int
    minor: int

    def __post_init__(self) -> None:
        if self.major < 0 or self.minor < 0:
            raise ValueError("API 版本号不能为负数")

    @classmethod
    def parse(cls, value: str) -> "ApiVersion":
        parts = str(value).split(".")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError(f"非法插件 API 版本：{value}")
        return cls(int(parts[0]), int(parts[1]))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


@dataclass(frozen=True)
class PluginDescriptor:
    plugin_id: str
    plugin_kind: PluginKind
    plugin_version: str
    api_version: ApiVersion
    compatible_api_min: ApiVersion
    compatible_api_max: ApiVersion
    supported_tasks: tuple[str, ...]
    input_contract: str
    output_contract: str
    thread_safe: bool
    config_schema_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.plugin_kind, PluginKind):
            raise TypeError("插件类型必须使用 PluginKind 枚举")
        for name in (
            "api_version",
            "compatible_api_min",
            "compatible_api_max",
        ):
            if not isinstance(getattr(self, name), ApiVersion):
                raise TypeError(f"{name} 必须使用 ApiVersion")
        for name in (
            "plugin_id",
            "plugin_version",
            "input_contract",
            "output_contract",
            "config_schema_id",
        ):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} 必须是字符串")
        if _PLUGIN_ID.fullmatch(self.plugin_id) is None:
            raise ValueError("插件标识必须以 tool-defect. 开头")
        if _SEMVER.fullmatch(self.plugin_version) is None:
            raise ValueError(f"插件版本不是语义版本：{self.plugin_version}")
        if self.api_version.major != self.compatible_api_min.major:
            raise ValueError("插件 API 版本与兼容范围主版本不一致")
        if self.compatible_api_min > self.api_version:
            raise ValueError("兼容范围下限不能高于插件 API 版本")
        if self.compatible_api_max <= self.api_version:
            raise ValueError("兼容范围上限必须高于插件 API 版本")
        if not isinstance(self.supported_tasks, tuple) or any(
            not isinstance(task, str) or not task
            for task in self.supported_tasks
        ):
            raise TypeError("支持任务必须是非空字符串元组")
        if not self.supported_tasks or len(set(self.supported_tasks)) != len(
            self.supported_tasks
        ):
            raise ValueError("插件必须声明非重复的支持任务")
        if not self.input_contract or not self.output_contract:
            raise ValueError("插件必须声明输入输出契约")
        if not isinstance(self.thread_safe, bool):
            raise TypeError("thread_safe 必须是布尔值")
        if not self.config_schema_id:
            raise ValueError("插件必须声明配置模式")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "plugin_kind": self.plugin_kind.value,
            "plugin_version": self.plugin_version,
            "api_version": str(self.api_version),
            "api_compatibility": {
                "minimum": str(self.compatible_api_min),
                "maximum_exclusive": str(self.compatible_api_max),
            },
            "supported_tasks": list(self.supported_tasks),
            "input_contract": self.input_contract,
            "output_contract": self.output_contract,
            "thread_safe": self.thread_safe,
            "config_schema_id": self.config_schema_id,
        }


def require_api_compatible(
    descriptor: PluginDescriptor,
    host_version: ApiVersion,
) -> None:
    if host_version.major != descriptor.api_version.major:
        raise PluginError.create(
            PluginErrorCode.MODEL_INCOMPATIBLE,
            "plugin_load",
            "插件 API 主版本不兼容",
            {
                "plugin_api_version": str(descriptor.api_version),
                "host_api_version": str(host_version),
            },
        )
    if not (
        descriptor.compatible_api_min
        <= host_version
        < descriptor.compatible_api_max
    ):
        raise PluginError.create(
            PluginErrorCode.MODEL_INCOMPATIBLE,
            "plugin_load",
            "插件未声明兼容当前 API 次版本",
            {
                "plugin_api_version": str(descriptor.api_version),
                "host_api_version": str(host_version),
            },
        )


def canonical_config_bytes(config: Mapping[str, Any]) -> bytes:
    if not isinstance(config, Mapping):
        raise TypeError("插件配置顶层必须是 JSON 对象")
    _validate_json_value(config, "config")
    try:
        encoded = json.dumps(
            config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("插件配置必须是有限值组成的 JSON 对象") from error
    return encoded.encode("utf-8")


def config_sha256(config: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_config_bytes(config)).hexdigest()


def _validate_json_value(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError(f"插件配置键必须是字符串：{path}")
            _validate_json_value(nested, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _validate_json_value(nested, f"{path}[{index}]")
        return
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"插件配置浮点数必须有限：{path}")
        return
    raise TypeError(
        f"插件配置包含非 JSON 类型：{path}={type(value).__name__}"
    )
