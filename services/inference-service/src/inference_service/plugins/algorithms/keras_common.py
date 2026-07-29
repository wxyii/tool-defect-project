"""Keras 算法插件共用的可信加载与生命周期。"""

from typing import Any, Mapping

from tool_defect.models.package import VerifiedModelPackage
from tool_defect.models.trusted_loader import TrustedKerasLoader
from tool_defect.plugin_api import (
    PluginError,
    PluginErrorCode,
    RuntimeContext,
)


class KerasAdapterBase:
    def __init__(
        self,
        *,
        loader: TrustedKerasLoader | None = None,
        custom_objects: Mapping[str, Any] | None = None,
    ):
        self._loader = loader or TrustedKerasLoader()
        self._custom_objects = dict(custom_objects or {})
        self._package: VerifiedModelPackage | None = None
        self._model: Any = None
        self._warmed = False
        self._closed = False
        self._warmup_shapes: Mapping[str, tuple[int, ...]] = {}

    def load(
        self,
        model_package: VerifiedModelPackage,
        context: RuntimeContext,
    ) -> None:
        self._require_not_closed()
        context.cancellation.raise_if_cancelled()
        self._validate_manifest(model_package)
        self._model = self._loader.load(
            model_package, self._custom_objects
        )
        self._package = model_package
        self._warmed = False

    def warmup(self) -> None:
        self._require_loaded()
        self._warmup_shapes = self._loader.warmup(
            self._model, self._package
        )
        self._warmed = True

    def health(self) -> Mapping[str, Any]:
        package = self._package
        return {
            "ready": bool(self._warmed and not self._closed),
            "model_version": (
                package.manifest.model_version if package is not None else None
            ),
            "model_sha256": (
                package.package_sha256 if package is not None else None
            ),
            "warmup_shapes": dict(self._warmup_shapes),
        }

    def close(self) -> None:
        self._model = None
        self._package = None
        self._warmed = False
        self._closed = True
        try:
            from tensorflow.keras import backend

            backend.clear_session()
        except Exception:
            pass

    def _require_ready(self) -> None:
        self._require_not_closed()
        if self._model is None or self._package is None or not self._warmed:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "inference",
                "模型尚未加载并预热",
            )

    def _require_loaded(self) -> None:
        self._require_not_closed()
        if self._model is None or self._package is None:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "model_warmup",
                "模型尚未加载",
            )

    def _require_not_closed(self) -> None:
        if self._closed:
            raise RuntimeError("算法插件已经关闭")

    def _validate_manifest(
        self,
        package: VerifiedModelPackage,
    ) -> None:
        raise NotImplementedError
