import math
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = PROJECT_ROOT / "services/inference-service/src"
if str(SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(SERVICE_SRC))

from inference_service.plugins.lifecycle import (
    AlgorithmLifecycleController,
    PreprocessorLifecycleController,
)
from tool_defect.plugin_api import (
    AlgorithmOutcome,
    AlgorithmOutput,
    ApiVersion,
    FrameBundle,
    ImageFrame,
    PluginDescriptor,
    PluginError,
    PluginErrorCode,
    PluginKind,
    PluginState,
    PreparedBatch,
    QualityStatus,
    config_sha256,
    require_api_compatible,
    validate_algorithm_output,
)


class PluginApiTests(unittest.TestCase):
    def test_descriptor_uses_exact_api_compatibility_range(self):
        descriptor = _descriptor()
        require_api_compatible(descriptor, ApiVersion(1, 1))

        with self.assertRaises(PluginError) as captured:
            require_api_compatible(descriptor, ApiVersion(2, 0))

        self.assertEqual(
            captured.exception.info.code,
            PluginErrorCode.MODEL_INCOMPATIBLE,
        )
        self.assertFalse(captured.exception.info.retryable)

    def test_descriptor_rejects_untyped_kind_and_mutable_tasks(self):
        values = _descriptor_values()
        values["plugin_kind"] = "preprocessor"
        with self.assertRaises(TypeError):
            PluginDescriptor(**values)

        values = _descriptor_values()
        values["supported_tasks"] = ["classification"]
        with self.assertRaises(TypeError):
            PluginDescriptor(**values)

    def test_config_hash_is_canonical_and_rejects_non_finite_values(self):
        first = config_sha256({"b": [2, 3], "a": 1})
        second = config_sha256({"a": 1, "b": [2, 3]})
        self.assertEqual(first, second)
        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")

        with self.assertRaises(ValueError):
            config_sha256({"invalid": math.nan})

    def test_image_frame_owns_immutable_pixel_memory(self):
        source = np.arange(27, dtype=np.uint8).reshape(3, 3, 3)
        source_attributes = {
            "image_role": "primary",
            "nested": {"roles": ["primary"]},
        }
        frame = ImageFrame(
            image_id="image-1",
            pixels=source,
            color_space="BGR",
            media_type="image/png",
            sha256="1" * 64,
            original_height=3,
            original_width=3,
            attributes=source_attributes,
        )
        source[:] = 0
        source_attributes["nested"]["roles"].append("changed")

        self.assertNotEqual(int(frame.pixels.sum()), 0)
        self.assertFalse(frame.pixels.flags.writeable)
        self.assertEqual(
            frame.attributes["nested"]["roles"], ("primary",)
        )
        with self.assertRaises(ValueError):
            frame.pixels[0, 0, 0] = 1
        with self.assertRaises(TypeError):
            frame.attributes["nested"]["other"] = True

    def test_memory_objects_require_enums_and_immutable_sequences(self):
        frame = _frame()
        with self.assertRaises(TypeError):
            FrameBundle(
                capture_id="capture-1",
                frames=[frame],
                recipe_id="recipe-1",
            )
        with self.assertRaises(TypeError):
            PreparedBatch(
                tensors={},
                coordinate_spaces={},
                transforms=(),
                artifacts={},
                quality_status="REJECTED",
                warnings=(),
                metadata={},
            )
        with self.assertRaises(TypeError):
            AlgorithmOutput(
                outcome="QUALIFIED",
                class_probabilities={},
                masks={},
                regions=(),
                scores={},
                warnings=(),
                metadata={"mask_coordinate_spaces": {}},
            )

    def test_algorithm_output_rejects_probability_conclusion_conflict(self):
        output = AlgorithmOutput(
            outcome=AlgorithmOutcome.QUALIFIED,
            class_probabilities={
                "qualified": 0.1,
                "unqualified": 0.9,
            },
            masks={},
            regions=(),
            scores={"confidence": 0.9},
            warnings=(),
            metadata={"mask_coordinate_spaces": {}},
        )

        with self.assertRaises(PluginError) as captured:
            validate_algorithm_output(output)

        self.assertEqual(
            captured.exception.info.code,
            PluginErrorCode.PLUGIN_BUG,
        )

    def test_preprocessor_lifecycle_converts_config_error_and_closes(self):
        plugin = _PreprocessorStub()
        lifecycle = PreprocessorLifecycleController(plugin)

        with self.assertRaises(PluginError) as captured:
            lifecycle.validate_config({"bad": True})

        self.assertEqual(
            captured.exception.info.code,
            PluginErrorCode.INPUT_INVALID,
        )
        self.assertEqual(lifecycle.state, PluginState.FAILED)
        lifecycle.close()
        lifecycle.close()
        self.assertEqual(lifecycle.state, PluginState.CLOSED)
        self.assertEqual(plugin.close_calls, 1)

    def test_algorithm_lifecycle_preserves_classified_plugin_error(self):
        lifecycle = AlgorithmLifecycleController(_AlgorithmStub())
        lifecycle.mark_config_validated()

        with self.assertRaises(PluginError) as captured:
            lifecycle.load(object(), object())

        self.assertEqual(
            captured.exception.info.code,
            PluginErrorCode.MODEL_INCOMPATIBLE,
        )
        self.assertEqual(lifecycle.state, PluginState.FAILED)


def _descriptor_values():
    return {
        "plugin_id": "tool-defect.test",
        "plugin_kind": PluginKind.PREPROCESSOR,
        "plugin_version": "1.2.3",
        "api_version": ApiVersion(1, 0),
        "compatible_api_min": ApiVersion(1, 0),
        "compatible_api_max": ApiVersion(2, 0),
        "supported_tasks": ("classification",),
        "input_contract": "frame-bundle/1.0",
        "output_contract": "prepared-batch/1.0",
        "thread_safe": True,
        "config_schema_id": "test/1.0",
    }


def _descriptor():
    return PluginDescriptor(**_descriptor_values())


def _frame():
    return ImageFrame(
        image_id="image-1",
        pixels=np.zeros((2, 2, 3), dtype=np.uint8),
        color_space="BGR",
        media_type="image/png",
        sha256="2" * 64,
        original_height=2,
        original_width=2,
        attributes={"image_role": "primary"},
    )


class _PreprocessorStub:
    def __init__(self):
        self.close_calls = 0

    def validate_config(self, config):
        raise ValueError("敏感内部配置错误")

    def close(self):
        self.close_calls += 1


class _AlgorithmStub:
    def load(self, package, context):
        raise PluginError.create(
            PluginErrorCode.MODEL_INCOMPATIBLE,
            "model_load",
            "模型不兼容",
        )


if __name__ == "__main__":
    unittest.main()
