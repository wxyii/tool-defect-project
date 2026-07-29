"""推理插件的稳定内部 API。"""

from tool_defect.plugin_api.context import (
    NeverCancelled,
    RuntimeContext,
)
from tool_defect.plugin_api.descriptor import (
    ApiVersion,
    PluginDescriptor,
    config_sha256,
    require_api_compatible,
)
from tool_defect.plugin_api.enums import (
    AlgorithmOutcome,
    PluginErrorCode,
    PluginKind,
    PluginState,
    QualityStatus,
)
from tool_defect.plugin_api.errors import (
    PluginError,
    PluginErrorInfo,
    classify_unexpected,
)
from tool_defect.plugin_api.memory import (
    AlgorithmOutput,
    FrameBundle,
    ImageFrame,
    PreparedBatch,
    TransformRecord,
)
from tool_defect.plugin_api.protocols import (
    AlgorithmPlugin,
    PreprocessorPlugin,
)
from tool_defect.plugin_api.validation import (
    inconclusive_output,
    validate_algorithm_output,
    validate_prepared_batch,
)

__all__ = [
    "AlgorithmOutcome",
    "AlgorithmOutput",
    "AlgorithmPlugin",
    "ApiVersion",
    "FrameBundle",
    "ImageFrame",
    "NeverCancelled",
    "PluginDescriptor",
    "PluginError",
    "PluginErrorCode",
    "PluginErrorInfo",
    "PluginKind",
    "PluginState",
    "PreparedBatch",
    "PreprocessorPlugin",
    "QualityStatus",
    "RuntimeContext",
    "TransformRecord",
    "classify_unexpected",
    "config_sha256",
    "inconclusive_output",
    "require_api_compatible",
    "validate_algorithm_output",
    "validate_prepared_batch",
]
