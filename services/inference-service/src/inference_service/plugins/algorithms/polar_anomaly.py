"""无标签极坐标异常算法适配器。"""

from types import SimpleNamespace
from typing import Any, Mapping

import numpy as np

from tool_defect.detection.polar_anomaly import (
    MODEL_VERSION,
    PolarAnomalyModel,
    detect_ring_result,
)
from tool_defect.models.package import VerifiedModelPackage
from tool_defect.plugin_api import (
    AlgorithmOutcome,
    AlgorithmOutput,
    ApiVersion,
    PluginDescriptor,
    PluginError,
    PluginErrorCode,
    PluginKind,
    PreparedBatch,
    RuntimeContext,
    classify_unexpected,
)
from tool_defect.plugin_api.validation import validate_algorithm_output


class PolarAnomalyAdapter:
    descriptor = PluginDescriptor(
        plugin_id="tool-defect.polar-anomaly",
        plugin_kind=PluginKind.ALGORITHM,
        plugin_version="1.0.0",
        api_version=ApiVersion(1, 0),
        compatible_api_min=ApiVersion(1, 0),
        compatible_api_max=ApiVersion(2, 0),
        supported_tasks=("anomaly_detection",),
        input_contract="prepared-batch/1.0",
        output_contract="algorithm-output/1.0",
        thread_safe=False,
        config_schema_id="polar-anomaly/1.0",
    )

    def __init__(self, model: PolarAnomalyModel | None = None):
        self._model = model
        self._warmed = False
        self._closed = False
        self._model_version = str(model.version) if model is not None else None
        self._model_sha256: str | None = None

    def load(
        self,
        model_package: VerifiedModelPackage,
        context: RuntimeContext,
    ) -> None:
        self._require_open()
        context.cancellation.raise_if_cancelled()
        try:
            model = PolarAnomalyModel.load(model_package.root / "model.json")
        except Exception as error:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "model_load",
                "极坐标异常模型不兼容",
                {"exception_type": type(error).__name__},
            ) from error
        self._model = model
        self._model_version = str(model.version)
        self._model_sha256 = model_package.package_sha256
        self._warmed = False

    def warmup(self) -> None:
        self._require_open()
        if self._model is None or self._model.version != MODEL_VERSION:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "model_warmup",
                "极坐标异常模型尚未加载或版本不兼容",
            )
        self._warmed = True

    def predict(
        self,
        prepared: PreparedBatch,
        context: RuntimeContext,
    ) -> AlgorithmOutput:
        self._require_open()
        context.cancellation.raise_if_cancelled()
        if self._model is None or not self._warmed:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "inference",
                "极坐标异常模型尚未预热",
            )
        try:
            denoised = prepared.tensors["polar_denoised"]
            ring = SimpleNamespace(
                denoised_polar_image=denoised,
                polar_image=denoised,
                raw_outer_boundary=prepared.artifacts["raw_outer_boundary"],
                outer_boundary=prepared.artifacts["outer_boundary"],
            )
            analysis, score_map, candidate_mask, regions, anomaly_score = (
                detect_ring_result(ring, self._model)
            )
        except ValueError as error:
            raise PluginError.create(
                PluginErrorCode.PREPROCESS_REJECTED,
                "inference",
                "极坐标结构不足以产生可信异常结果",
                {"exception_type": type(error).__name__},
            ) from error
        except Exception as error:
            raise classify_unexpected(error, "inference") from error
        region_payload = tuple(
            {
                "region_id": region.region_id,
                "coordinate_space": "polar_normalized",
                "geometry_type": "polar_interval",
                "geometry": {
                    "start_angle_degrees": region.start_angle_degrees,
                    "end_angle_degrees": region.end_angle_degrees,
                    "radial_start": region.radial_start,
                    "radial_end": region.radial_end,
                },
                "scores": {
                    "peak": region.peak_score,
                    "mean": region.mean_score,
                },
                "attributes": {"area_pixels": region.area},
            }
            for region in regions
        )
        outcome = (
            AlgorithmOutcome.UNQUALIFIED
            if regions or anomaly_score >= self._model.threshold
            else AlgorithmOutcome.QUALIFIED
        )
        output = AlgorithmOutput(
            outcome=outcome,
            class_probabilities={},
            masks={"defect": candidate_mask.astype(np.uint8)},
            regions=region_payload,
            scores={
                "anomaly_score": float(anomaly_score),
                "anomaly_threshold": float(self._model.threshold),
                "period_count": float(analysis.period_count),
            },
            warnings=(),
            metadata={
                "mask_coordinate_spaces": {
                    "defect": "polar_normalized"
                },
                "phase_offset": int(analysis.phase_offset),
            },
        )
        validate_algorithm_output(output)
        return output

    def health(self) -> Mapping[str, Any]:
        return {
            "ready": bool(self._warmed and not self._closed),
            "model_version": self._model_version,
            "model_sha256": self._model_sha256,
        }

    def close(self) -> None:
        self._model = None
        self._warmed = False
        self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("算法插件已经关闭")
