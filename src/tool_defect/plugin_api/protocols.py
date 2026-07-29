"""预处理与算法插件的结构化协议。"""

from typing import Any, Mapping, Protocol, TYPE_CHECKING

from tool_defect.plugin_api.context import RuntimeContext
from tool_defect.plugin_api.descriptor import PluginDescriptor
from tool_defect.plugin_api.memory import (
    AlgorithmOutput,
    FrameBundle,
    PreparedBatch,
)

if TYPE_CHECKING:
    from tool_defect.models.package import VerifiedModelPackage


class PreprocessorPlugin(Protocol):
    descriptor: PluginDescriptor

    def validate_config(self, config: Mapping[str, Any]) -> None:
        ...

    def prepare(
        self,
        frames: FrameBundle,
        context: RuntimeContext,
    ) -> PreparedBatch:
        ...

    def health(self) -> Mapping[str, Any]:
        ...

    def close(self) -> None:
        ...


class AlgorithmPlugin(Protocol):
    descriptor: PluginDescriptor

    def load(
        self,
        model_package: "VerifiedModelPackage",
        context: RuntimeContext,
    ) -> None:
        ...

    def warmup(self) -> None:
        ...

    def predict(
        self,
        prepared: PreparedBatch,
        context: RuntimeContext,
    ) -> AlgorithmOutput:
        ...

    def health(self) -> Mapping[str, Any]:
        ...

    def close(self) -> None:
        ...
