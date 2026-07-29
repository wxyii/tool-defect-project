"""自适应环形区域预处理插件。"""

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
    affine_record,
    gray_model_tensor,
    primary_bgr_frame,
    process_ring,
    resize_record,
    ring_artifacts,
    validate_common_config,
)


class AdaptiveAnnularPreprocessor:
    descriptor = PluginDescriptor(
        plugin_id="tool-defect.adaptive-annular",
        plugin_kind=PluginKind.PREPROCESSOR,
        plugin_version="1.0.0",
        api_version=ApiVersion(1, 0),
        compatible_api_min=ApiVersion(1, 0),
        compatible_api_max=ApiVersion(2, 0),
        supported_tasks=("classification", "segmentation"),
        input_contract="frame-bundle/1.0",
        output_contract="prepared-batch/1.0",
        thread_safe=False,
        config_schema_id="adaptive-annular/1.0",
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
        validate_common_config(config)

    def prepare(
        self,
        frames: FrameBundle,
        context: RuntimeContext,
    ) -> PreparedBatch:
        self._require_open()
        context.cancellation.raise_if_cancelled()
        frame = primary_bgr_frame(frames)
        ring = process_ring(frame, self._config)
        height = int(self._config["model_height"])
        width = int(self._config["model_width"])
        tensor = gray_model_tensor(ring.annular_roi, height, width)
        identity = TransformRecord(
            transform_type="identity_mask",
            source_space="rectified",
            target_space="annular_rectified",
            parameters={"shape": list(ring.annular_roi.shape[:2])},
            artifact_refs={},
            invertible=True,
            inverse_error_pixels=0.0,
        )
        return PreparedBatch(
            tensors={"model_input": tensor},
            coordinate_spaces={
                "model_input": {
                    "name": "model_input",
                    "shape": [height, width],
                }
            },
            transforms=(
                affine_record(frame, ring),
                identity,
                resize_record(
                    "annular_rectified",
                    ring.annular_roi.shape[:2],
                    (height, width),
                ),
            ),
            artifacts=ring_artifacts(ring),
            quality_status=QualityStatus.OK,
            warnings=(),
            metadata={
                "source_image_id": frame.image_id,
                "preprocessor": self.descriptor.plugin_id,
            },
        )

    def health(self) -> Mapping[str, Any]:
        return {"ready": not self._closed}

    def close(self) -> None:
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("预处理插件已经关闭")
