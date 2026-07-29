"""兼容现有灰度缩放行为的内存预处理插件。"""

from typing import Any, Mapping

from tool_defect.plugin_api import (
    ApiVersion,
    FrameBundle,
    PluginDescriptor,
    PluginKind,
    PreparedBatch,
    QualityStatus,
    RuntimeContext,
    TransformRecord,
    config_sha256,
)

from inference_service.plugins.preprocessors.common import (
    legacy_gray_model_tensor,
    primary_bgr_frame,
)


class BasicGrayResizePreprocessor:
    descriptor = PluginDescriptor(
        plugin_id="tool-defect.basic-gray-resize",
        plugin_kind=PluginKind.PREPROCESSOR,
        plugin_version="1.0.0",
        api_version=ApiVersion(1, 0),
        compatible_api_min=ApiVersion(1, 0),
        compatible_api_max=ApiVersion(2, 0),
        supported_tasks=("classification", "segmentation"),
        input_contract="frame-bundle/1.0",
        output_contract="prepared-batch/1.0",
        thread_safe=True,
        config_schema_id="basic-gray-resize/1.0",
    )

    def __init__(self, config: Mapping[str, Any]):
        self.validate_config(config)
        self._config = dict(config)
        self._configuration_sha256 = config_sha256(self._config)
        self._closed = False

    @property
    def configuration_sha256(self) -> str:
        return self._configuration_sha256

    def validate_config(self, config: Mapping[str, Any]) -> None:
        if set(config) != {"model_height", "model_width"}:
            raise ValueError("灰度缩放配置字段不完整或包含未知字段")
        for name in ("model_height", "model_width"):
            if (
                isinstance(config[name], bool)
                or not isinstance(config[name], int)
                or config[name] < 2
            ):
                raise ValueError("模型输入尺寸必须是至少为 2 的整数")

    def prepare(
        self,
        frames: FrameBundle,
        context: RuntimeContext,
    ) -> PreparedBatch:
        self._require_open()
        context.cancellation.raise_if_cancelled()
        frame = primary_bgr_frame(frames)
        height = int(self._config["model_height"])
        width = int(self._config["model_width"])
        tensor = legacy_gray_model_tensor(frame, height, width)
        transform = TransformRecord(
            transform_type="resize",
            source_space="original",
            target_space="model_input",
            parameters={
                "source_shape": list(frame.pixels.shape[:2]),
                "target_shape": [height, width],
                "image_interpolation": "INTER_AREA",
                "mask_interpolation": "INTER_NEAREST",
            },
            artifact_refs={},
            invertible=True,
            inverse_error_pixels=1.0,
        )
        return PreparedBatch(
            tensors={"model_input": tensor},
            coordinate_spaces={
                "model_input": {
                    "name": "model_input",
                    "shape": [height, width],
                }
            },
            transforms=(transform,),
            artifacts={},
            quality_status=QualityStatus.OK,
            warnings=(),
            metadata={
                "source_image_id": frame.image_id,
                "color_conversion": "BGR_TO_GRAY_TO_RGB",
            },
        )

    def health(self) -> Mapping[str, Any]:
        return {"ready": not self._closed}

    def close(self) -> None:
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("预处理插件已经关闭")
