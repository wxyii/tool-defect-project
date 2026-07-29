"""只接受已验证模型包的 Keras 加载器。"""

import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from tool_defect.models.package import (
    VerifiedModelPackage,
    recheck_verified_package,
)
from tool_defect.plugin_api import PluginError, PluginErrorCode


_SAFE_SERIALIZED_CLASSES = {
    "Activation",
    "Add",
    "BatchNormalization",
    "Concatenate",
    "Conv2D",
    "Dense",
    "Dropout",
    "Flatten",
    "Functional",
    "GlobalAveragePooling2D",
    "GlobalMaxPooling2D",
    "GlorotUniform",
    "HeNormal",
    "InputLayer",
    "L2",
    "MaxPooling2D",
    "Multiply",
    "Ones",
    "Reshape",
    "SeparableConv2D",
    "TFOpLambda",
    "UpSampling2D",
    "Zeros",
}
_ALWAYS_FORBIDDEN = {
    "Lambda",
    "PythonFunction",
    "PyFunc",
}
_SAFE_TF_OP_FUNCTIONS = {
    "__operators__.add",
    "math.multiply",
    "math.reduce_max",
    "math.reduce_mean",
    "math.sigmoid",
    "nn.relu",
}
_SAFE_MODULE_PREFIXES = (
    "keras.",
    "tensorflow.keras.",
)


class TrustedKerasLoader:
    def __init__(
        self,
        *,
        allowed_serialized_classes: set[str] | None = None,
    ):
        self._allowed = set(
            allowed_serialized_classes or _SAFE_SERIALIZED_CLASSES
        )

    def inspect_model_json(
        self,
        architecture: str,
        allowed_custom_objects: Mapping[str, Any],
    ) -> tuple[str, ...]:
        if any(
            not isinstance(name, str) or not name
            for name in allowed_custom_objects
        ):
            raise _model_error("自定义对象白名单名称非法")
        try:
            payload = json.loads(architecture)
        except json.JSONDecodeError as error:
            raise _model_error("模型结构 JSON 无法解析") from error
        classes: set[str] = set()
        modules: set[str] = set()
        tf_op_functions: set[str] = set()

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                class_name = value.get("class_name")
                if isinstance(class_name, str):
                    classes.add(class_name)
                    if class_name == "TFOpLambda":
                        config = value.get("config")
                        function = (
                            config.get("function")
                            if isinstance(config, dict)
                            else None
                        )
                        if not isinstance(function, str):
                            raise _model_error(
                                "TFOpLambda 缺少可验证函数名"
                            )
                        tf_op_functions.add(function)
                module = value.get("module")
                if isinstance(module, str):
                    modules.add(module)
                for nested in value.values():
                    walk(nested)
            elif isinstance(value, list):
                for nested in value:
                    walk(nested)

        walk(payload)
        forbidden = classes.intersection(_ALWAYS_FORBIDDEN)
        if forbidden:
            raise _model_error(
                "模型结构包含禁止的可执行层",
                {"classes": sorted(forbidden)},
            )
        unsafe_modules = {
            module
            for module in modules
            if not module.startswith(_SAFE_MODULE_PREFIXES)
        }
        if unsafe_modules:
            raise _model_error(
                "模型结构引用了不受信模块",
                {"modules": sorted(unsafe_modules)},
            )
        unsafe_functions = tf_op_functions.difference(
            _SAFE_TF_OP_FUNCTIONS
        )
        if unsafe_functions:
            raise _model_error(
                "模型结构引用了未批准的张量函数",
                {"functions": sorted(unsafe_functions)},
            )
        allowed = self._allowed.union(allowed_custom_objects)
        unknown = classes.difference(allowed)
        if unknown:
            raise _model_error(
                "模型结构包含未知对象",
                {"classes": sorted(unknown)},
            )
        return tuple(sorted(classes))

    def load(
        self,
        package: VerifiedModelPackage,
        allowed_custom_objects: Mapping[str, Any],
    ) -> Any:
        recheck_verified_package(package)
        architecture = (package.root / "model.json").read_text(
            encoding="utf-8"
        )
        self.inspect_model_json(architecture, allowed_custom_objects)
        try:
            from tensorflow.keras.models import model_from_json

            model = model_from_json(
                architecture,
                custom_objects=dict(allowed_custom_objects),
            )
            model.load_weights(package.root / "weights.h5")
        except Exception as error:
            raise _model_error(
                "模型结构与权重无法安全加载",
                {"exception_type": type(error).__name__},
            ) from error
        self._validate_loaded_model(model, package)
        return model

    def warmup(
        self,
        model: Any,
        package: VerifiedModelPackage,
    ) -> Mapping[str, tuple[int, ...]]:
        input_spec = package.manifest.input_spec
        dtype = np.dtype(input_spec.dtype)
        sample_path = package.root / "warmup-input.npy"
        expected_path = package.root / "warmup-expected.json"
        if sample_path.exists() != expected_path.exists():
            raise _model_error("固定预热输入和期望结果必须成对存在")
        if sample_path.exists():
            try:
                sample = np.load(sample_path, allow_pickle=False)
            except Exception as error:
                raise _model_error(
                    "固定预热输入无法安全读取",
                    {"exception_type": type(error).__name__},
                ) from error
        else:
            sample = np.zeros((1,) + input_spec.shape, dtype=dtype)
        if sample.dtype != dtype or sample.shape != (1,) + input_spec.shape:
            raise _model_error(
                "固定预热输入与模型清单不一致",
                {
                    "expected_shape": [1, *input_spec.shape],
                    "actual_shape": list(sample.shape),
                    "expected_dtype": str(dtype),
                    "actual_dtype": str(sample.dtype),
                },
            )
        if not np.all(np.isfinite(sample)):
            raise _model_error("固定预热输入包含非有限值")
        if (
            float(np.min(sample)) < input_spec.value_range[0]
            or float(np.max(sample)) > input_spec.value_range[1]
        ):
            raise _model_error("固定预热输入超出模型清单数值范围")
        try:
            predictions = model.predict(sample, verbose=0)
        except Exception as error:
            raise _model_error(
                "模型固定形状预热失败",
                {"exception_type": type(error).__name__},
            ) from error
        values = predictions if isinstance(predictions, (list, tuple)) else [
            predictions
        ]
        if len(values) != len(package.manifest.output_names):
            raise _model_error("模型预热输出数量不匹配")
        shapes = {
            name: tuple(int(size) for size in np.asarray(value).shape)
            for name, value in zip(package.manifest.output_names, values)
        }
        if any(
            not np.all(np.isfinite(np.asarray(value)))
            for value in values
        ):
            raise _model_error("模型预热输出包含非有限值")
        if expected_path.exists():
            expected = _load_warmup_expectations(expected_path)
            actual = {name: list(shape) for name, shape in shapes.items()}
            if expected != actual:
                raise _model_error(
                    "固定预热输出形状与包内期望不一致",
                    {"expected": expected, "actual": actual},
                )
        return shapes

    @staticmethod
    def _validate_loaded_model(
        model: Any,
        package: VerifiedModelPackage,
    ) -> None:
        manifest = package.manifest
        input_shape = tuple(int(value) for value in model.input_shape[1:])
        if input_shape != manifest.input_spec.shape:
            raise _model_error(
                "加载后模型输入形状与清单不一致",
                {
                    "manifest": list(manifest.input_spec.shape),
                    "model": list(input_shape),
                },
            )
        if tuple(model.output_names) != manifest.output_names:
            raise _model_error(
                "加载后模型输出名与清单不一致",
                {
                    "manifest": list(manifest.output_names),
                    "model": list(model.output_names),
                },
            )


def _model_error(
    message: str,
    details: Mapping[str, Any] | None = None,
) -> PluginError:
    return PluginError.create(
        PluginErrorCode.MODEL_INCOMPATIBLE,
        "model_load",
        message,
        details,
    )


def _load_warmup_expectations(path: Path) -> dict[str, list[int]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _model_error("固定预热期望无法解析") from error
    if not isinstance(payload, dict) or set(payload) != {"output_shapes"}:
        raise _model_error(
            "固定预热期望必须只包含 output_shapes"
        )
    shapes = payload["output_shapes"]
    if not isinstance(shapes, dict):
        raise _model_error("固定预热输出形状必须是对象")
    result: dict[str, list[int]] = {}
    for name, shape in shapes.items():
        if (
            not isinstance(name, str)
            or not isinstance(shape, list)
                or any(
                    isinstance(size, bool)
                    or not isinstance(size, int)
                    or size <= 0
                    for size in shape
                )
        ):
            raise _model_error("固定预热输出形状非法")
        result[name] = shape
    return result
