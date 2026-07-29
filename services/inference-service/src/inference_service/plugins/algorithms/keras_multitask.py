"""Keras 分类与分割双任务算法适配器。"""

from tool_defect.inference.prediction_core import (
    named_model_outputs,
    normalize_multitask_outputs,
)
from tool_defect.models.package import VerifiedModelPackage
from tool_defect.plugin_api import (
    AlgorithmOutput,
    ApiVersion,
    PluginDescriptor,
    PluginError,
    PluginErrorCode,
    PluginKind,
    PreparedBatch,
    RuntimeContext,
)

from inference_service.plugins.algorithms.keras_common import KerasAdapterBase


class KerasMultitaskAdapter(KerasAdapterBase):
    descriptor = PluginDescriptor(
        plugin_id="tool-defect.keras-multitask",
        plugin_kind=PluginKind.ALGORITHM,
        plugin_version="1.0.0",
        api_version=ApiVersion(1, 0),
        compatible_api_min=ApiVersion(1, 0),
        compatible_api_max=ApiVersion(2, 0),
        supported_tasks=("classification", "segmentation"),
        input_contract="prepared-batch/1.0",
        output_contract="algorithm-output/1.0",
        thread_safe=False,
        config_schema_id="keras-multitask/1.0",
    )

    def predict(
        self,
        prepared: PreparedBatch,
        context: RuntimeContext,
    ) -> AlgorithmOutput:
        self._require_ready()
        context.cancellation.raise_if_cancelled()
        try:
            outputs = named_model_outputs(
                self._model, prepared.tensors["model_input"]
            )
            return normalize_multitask_outputs(
                outputs,
                self._package.manifest.label_map,
                coordinate_space="model_input",
            )
        except PluginError:
            raise
        except Exception as error:
            raise PluginError.create(
                PluginErrorCode.PLUGIN_BUG,
                "inference",
                "双任务模型输出不符合协议",
                {"exception_type": type(error).__name__},
            ) from error

    def _validate_manifest(
        self,
        package: VerifiedModelPackage,
    ) -> None:
        if package.manifest.output_names != ("cla_out", "seg_out"):
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "model_load",
                "双任务模型输出必须按 cla_out、seg_out 排列",
            )
