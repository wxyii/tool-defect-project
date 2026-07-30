"""不泄露路径和凭据的冻结运行时健康投影。"""

import re
from typing import Any, Mapping

from inference_service.model_runtime.supervisor import RuntimeSupervisor
from inference_service.telemetry import MetricRegistry


_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


class RuntimeHealthService:
    def __init__(
        self,
        supervisor: RuntimeSupervisor,
        *,
        runtime_version: str,
        metrics: MetricRegistry | None = None,
        purpose: str = "production",
    ):
        if (
            not isinstance(runtime_version, str)
            or _VERSION.fullmatch(runtime_version) is None
        ):
            raise ValueError("运行时版本不符合冻结契约")
        if (
            not isinstance(purpose, str)
            or _VERSION.fullmatch(purpose) is None
        ):
            raise ValueError("运行目的不符合低基数指标约束")
        self._supervisor = supervisor
        self._runtime_version = runtime_version
        self._metrics = metrics or MetricRegistry(
            {"model_version", "purpose"}
        )
        self._purpose = purpose

    def readiness(self) -> Mapping[str, Any]:
        models = self.models()["models"]
        return {
            "ready": bool(models) and all(
                model["ready"] for model in models
            ),
            "runtime_version": self._runtime_version,
        }

    def models(self) -> Mapping[str, tuple[dict[str, Any], ...]]:
        result = []
        for health in self._supervisor.health():
            model_version = health.get("model_version")
            model_sha256 = health.get("model_sha256")
            if not isinstance(model_version, str) or not isinstance(
                model_sha256, str
            ):
                continue
            ready = bool(health.get("ready", False))
            self._metrics.set_gauge(
                "tool_defect_inference_ready",
                1 if ready else 0,
                labels={
                    "model_version": model_version,
                    "purpose": self._purpose,
                },
            )
            result.append(
                {
                    "model_version": model_version,
                    "sha256": model_sha256,
                    "ready": ready,
                }
            )
        return {
            "models": tuple(
                sorted(
                    result,
                    key=lambda item: (
                        item["model_version"],
                        item["sha256"],
                    ),
                )
            )
        }
