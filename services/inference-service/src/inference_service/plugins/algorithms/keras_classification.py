"""Keras 二分类算法适配器。"""

from typing import Any, Mapping

from tool_defect.inference.prediction_core import (
    named_model_outputs,
    normalize_classification_output,
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


class KerasClassificationAdapter(KerasAdapterBase):
    descriptor = PluginDescriptor(
        plugin_id="tool-defect.keras-classification",
        plugin_kind=PluginKind.ALGORITHM,
        plugin_version="1.0.0",
        api_version=ApiVersion(1, 0),
        compatible_api_min=ApiVersion(1, 0),
        compatible_api_max=ApiVersion(2, 0),
        supported_tasks=("classification",),
        input_contract="prepared-batch/1.0",
        output_contract="algorithm-output/1.0",
        thread_safe=False,
        config_schema_id="keras-classification/1.0",
    )

    def predict(
        self,
        prepared: PreparedBatch,
        context: RuntimeContext,
    ) -> AlgorithmOutput:
        self._require_ready()
        context.cancellation.raise_if_cancelled()
        try:
            tensor = prepared.tensors["model_input"]
            outputs = named_model_outputs(self._model, tensor)
            output_name = self._package.manifest.output_names[0]
            return normalize_classification_output(
                outputs[output_name],
                self._package.manifest.label_map,
            )
        except PluginError:
            raise
        except Exception as error:
            raise PluginError.create(
                PluginErrorCode.PLUGIN_BUG,
                "inference",
                "分类模型输出不符合协议",
                {"exception_type": type(error).__name__},
            ) from error

    def _validate_manifest(
        self,
        package: VerifiedModelPackage,
    ) -> None:
        if len(package.manifest.output_names) != 1:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "model_load",
                "分类模型必须只有一个输出",
            )
