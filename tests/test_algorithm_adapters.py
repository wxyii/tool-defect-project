from pathlib import Path
from types import SimpleNamespace
import hashlib
import sys
import tempfile
import time
import unittest
from unittest import mock

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICE_SRC = PROJECT_ROOT / "services/inference-service/src"
if str(SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(SERVICE_SRC))

from inference_service.plugins.algorithms.keras_multitask import (
    KerasMultitaskAdapter,
)
from inference_service.plugins.algorithms.polar_anomaly import (
    PolarAnomalyAdapter,
)
from inference_service.plugins.cache import (
    CachedPreprocessor,
    PreparedBatchCache,
)
from inference_service.plugins.preprocessors import (
    AdaptiveAnnularPreprocessor,
    BasicGrayResizePreprocessor,
    BoundaryNormalizedPreprocessor,
    PolarDenoisePreprocessor,
)
from tool_defect.data.preprocess import load_image_batch
from tool_defect.detection.polar_anomaly import MODEL_VERSION
from tool_defect.inference.prediction_core import (
    normalize_multitask_outputs,
)
from tool_defect.inference.result_normalization import normalize_result
from tool_defect.models.package import (
    ModelInputSpec,
    ModelManifest,
    PreprocessorRequirement,
    VerifiedModelPackage,
)
from tool_defect.plugin_api import (
    AlgorithmOutcome,
    AlgorithmOutput,
    FrameBundle,
    ImageFrame,
    NeverCancelled,
    PreparedBatch,
    QualityStatus,
    RuntimeContext,
)


class AlgorithmAdapterTests(unittest.TestCase):
    def test_basic_gray_resize_preserves_existing_pixel_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pixels = np.asarray(
                [
                    [[0, 10, 200], [20, 30, 40], [255, 100, 0]],
                    [[7, 8, 9], [80, 90, 100], [1, 2, 3]],
                    [[200, 180, 20], [4, 250, 30], [60, 50, 40]],
                ],
                dtype=np.uint8,
            )
            image_path = root / "source.png"
            success, encoded = cv2.imencode(".png", pixels)
            self.assertTrue(success)
            image_path.write_bytes(encoded.tobytes())
            expected = load_image_batch(image_path, image_size=5)
            plugin = BasicGrayResizePreprocessor(
                {"model_height": 5, "model_width": 5}
            )

            prepared = plugin.prepare(
                _bundle(
                    pixels,
                    hashlib.sha256(encoded).hexdigest(),
                    encoded_bytes=encoded.tobytes(),
                ),
                _context(root),
            )

            np.testing.assert_array_equal(
                prepared.tensors["model_input"], expected
            )
            self.assertFalse(
                prepared.tensors["model_input"].flags.writeable
            )

    def test_four_preprocessors_are_deterministic_and_record_geometry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pixels = np.full((32, 32, 3), 96, dtype=np.uint8)
            bundle = _bundle(pixels, "3" * 64)
            context = _context(root)
            ring = _fake_ring()
            config = {
                "geometry_output_size": 64,
                "angle_samples": 64,
                "model_height": 8,
                "model_width": 8,
            }
            cases = (
                (
                    AdaptiveAnnularPreprocessor(config),
                    "inference_service.plugins.preprocessors."
                    "adaptive_annular.process_ring",
                ),
                (
                    BoundaryNormalizedPreprocessor(config),
                    "inference_service.plugins.preprocessors."
                    "boundary_normalized.process_ring",
                ),
                (
                    PolarDenoisePreprocessor(config),
                    "inference_service.plugins.preprocessors."
                    "polar_denoise.process_ring",
                ),
            )
            for plugin, patch_target in cases:
                with self.subTest(plugin=plugin.descriptor.plugin_id):
                    with mock.patch(
                        patch_target, return_value=ring
                    ):
                        first = plugin.prepare(bundle, context)
                        second = plugin.prepare(bundle, context)
                    self.assertEqual(
                        first.quality_status, QualityStatus.OK
                    )
                    self.assertTrue(first.transforms)
                    for name in first.tensors:
                        np.testing.assert_array_equal(
                            first.tensors[name], second.tensors[name]
                        )

    def test_multitask_empty_mask_keeps_unqualified_and_adds_warning(self):
        segmentation = np.zeros((1, 4, 4, 2), dtype=np.float32)
        segmentation[..., 0] = 1.0

        output = normalize_multitask_outputs(
            {
                "cla_out": np.asarray([[0.1, 0.9]], dtype=np.float32),
                "seg_out": segmentation,
            },
            {0: "qualified", 1: "unqualified"},
            coordinate_space="model_input",
        )

        self.assertEqual(output.outcome, AlgorithmOutcome.UNQUALIFIED)
        self.assertIn("UNQUALIFIED_EMPTY_MASK", output.warnings)
        self.assertFalse(np.any(output.masks["defect"]))

    def test_multitask_adapter_delegates_to_existing_output_normalizer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = _verified_package(root)
            loader = _FakeKerasLoader()
            plugin = KerasMultitaskAdapter(loader=loader)
            context = _context(root)
            prepared = PreparedBatch(
                tensors={
                    "model_input": np.zeros(
                        (1, 2, 2, 3), dtype=np.float32
                    )
                },
                coordinate_spaces={
                    "model_input": {
                        "name": "model_input",
                        "shape": [2, 2],
                    }
                },
                transforms=(),
                artifacts={},
                quality_status=QualityStatus.OK,
                warnings=(),
                metadata={},
            )
            plugin.load(package, context)
            plugin.warmup()

            output = plugin.predict(prepared, context)

            self.assertEqual(output.outcome, AlgorithmOutcome.UNQUALIFIED)
            self.assertIn("UNQUALIFIED_EMPTY_MASK", output.warnings)
            self.assertEqual(loader.load_calls, 1)
            self.assertEqual(loader.warmup_calls, 1)

    def test_polar_adapter_delegates_to_existing_detector(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = SimpleNamespace(
                version=MODEL_VERSION,
                threshold=0.5,
            )
            plugin = PolarAnomalyAdapter(model=model)
            plugin.warmup()
            prepared = PreparedBatch(
                tensors={
                    "polar_denoised": np.zeros(
                        (8, 32, 3), dtype=np.uint8
                    )
                },
                coordinate_spaces={
                    "polar_denoised": {
                        "name": "polar_normalized",
                        "shape": [8, 32],
                    }
                },
                transforms=(),
                artifacts={
                    "raw_outer_boundary": np.ones(32, dtype=np.float32),
                    "outer_boundary": np.ones(32, dtype=np.float32),
                },
                quality_status=QualityStatus.OK,
                warnings=(),
                metadata={},
            )
            detector_result = (
                SimpleNamespace(period_count=16, phase_offset=2),
                np.zeros((8, 32), dtype=np.float32),
                np.zeros((8, 32), dtype=np.uint8),
                (),
                0.1,
            )
            with mock.patch(
                "inference_service.plugins.algorithms.polar_anomaly."
                "detect_ring_result",
                return_value=detector_result,
            ) as detector:
                output = plugin.predict(prepared, _context(root))

            detector.assert_called_once()
            self.assertEqual(output.outcome, AlgorithmOutcome.QUALIFIED)
            self.assertEqual(output.scores["period_count"], 16.0)

    def test_mask_is_mapped_back_to_original_coordinates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pixels = np.zeros((4, 4, 3), dtype=np.uint8)
            prepared = BasicGrayResizePreprocessor(
                {"model_height": 2, "model_width": 2}
            ).prepare(_bundle(pixels, "4" * 64), _context(root))
            output = AlgorithmOutput(
                outcome=AlgorithmOutcome.UNQUALIFIED,
                class_probabilities={},
                masks={
                    "defect": np.asarray(
                        [[1, 0], [0, 0]], dtype=np.uint8
                    )
                },
                regions=(),
                scores={},
                warnings=(),
                metadata={
                    "mask_coordinate_spaces": {
                        "defect": "model_input"
                    }
                },
            )

            normalized = normalize_result(prepared, output)

            mask = normalized.artifacts["defect"].pixels
            self.assertEqual(mask.shape, (4, 4))
            self.assertTrue(np.any(mask[:2, :2]))
            self.assertFalse(np.any(mask[2:, 2:]))

    def test_internal_polar_region_is_normalized_to_frozen_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = BasicGrayResizePreprocessor(
                {"model_height": 2, "model_width": 2}
            ).prepare(
                _bundle(np.zeros((4, 4, 3), dtype=np.uint8), "8" * 64),
                _context(root),
            )
            output = AlgorithmOutput(
                outcome=AlgorithmOutcome.UNQUALIFIED,
                class_probabilities={},
                masks={},
                regions=(
                    {
                        "region_id": 1,
                        "coordinate_space": "polar_normalized",
                        "geometry_type": "polar_interval",
                        "geometry": {
                            "start_angle_degrees": 10.0,
                            "end_angle_degrees": 20.0,
                            "radial_start": 0.1,
                            "radial_end": 0.4,
                        },
                        "scores": {"peak": 0.9},
                        "attributes": {"area_pixels": 12},
                    },
                ),
                scores={"anomaly_score": 0.9},
                warnings=(),
                metadata={"mask_coordinate_spaces": {}},
            )

            normalized = normalize_result(prepared, output)

            region = normalized.payload["regions"][0]
            self.assertEqual(region["coordinate_space"], "POLAR")
            self.assertEqual(
                region["geometry_type"], "POLAR_INTERVAL"
            )
            self.assertEqual(
                set(region["geometry"]),
                {
                    "angle_start_degrees",
                    "angle_end_degrees",
                    "radial_start",
                    "radial_end",
                },
            )
            self.assertEqual(
                normalized.payload["class_probabilities"],
                {"qualified": 0.5, "unqualified": 0.5},
            )

    def test_cache_hits_invalidates_by_code_and_rebuilds_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = PreparedBatchCache(root / "cache")
            config = {"model_height": 3, "model_width": 3}
            plugin = BasicGrayResizePreprocessor(config)
            plugin.prepare = mock.Mock(wraps=plugin.prepare)
            cached = CachedPreprocessor(plugin, config, cache)
            bundle = _bundle(
                np.zeros((4, 4, 3), dtype=np.uint8), "5" * 64
            )

            first = cached.prepare(bundle, _context(root, code="code:v1"))
            second = cached.prepare(bundle, _context(root, code="code:v1"))

            self.assertFalse(first is second)
            self.assertTrue(cached.last_cache_hit)
            self.assertEqual(plugin.prepare.call_count, 1)
            available = tuple((root / "cache").glob("*.available.npz"))
            self.assertEqual(len(available), 1)
            available[0].write_bytes(b"corrupted-cache")

            rebuilt = cached.prepare(
                bundle, _context(root, code="code:v1")
            )

            self.assertFalse(cached.last_cache_hit)
            self.assertEqual(plugin.prepare.call_count, 2)
            np.testing.assert_array_equal(
                rebuilt.tensors["model_input"],
                first.tensors["model_input"],
            )
            cached.prepare(bundle, _context(root, code="code:v2"))
            self.assertFalse(cached.last_cache_hit)
            self.assertEqual(plugin.prepare.call_count, 3)
            self.assertEqual(
                len(tuple((root / "cache").glob("*.available.npz"))),
                2,
            )
            self.assertEqual(
                len(tuple((root / "cache").glob("*.invalid.npz"))),
                1,
            )


def _bundle(pixels, sha256, *, encoded_bytes=None):
    height, width = pixels.shape[:2]
    return FrameBundle(
        capture_id="capture-1",
        frames=(
            ImageFrame(
                image_id="image-1",
                pixels=pixels,
                color_space="BGR",
                media_type="image/png",
                sha256=sha256,
                original_height=height,
                original_width=width,
                attributes={"image_role": "primary"},
                encoded_bytes=encoded_bytes,
            ),
        ),
        recipe_id="recipe-1",
    )


def _context(root, *, code="code:test"):
    return RuntimeContext(
        run_id="run-1",
        attempt_id="attempt-1",
        pipeline_version="pipeline-1",
        config_sha256="sha256:" + "6" * 64,
        code_signature=code,
        runtime_slot_id="slot-1",
        device="cpu",
        temp_dir=Path(root).resolve(),
        random_seed=0,
        deadline_monotonic=time.monotonic() + 60,
        cancellation=NeverCancelled(),
    )


def _fake_ring():
    size = 32
    angles = 64
    polar = np.full((16, angles, 3), 96, dtype=np.uint8)
    return SimpleNamespace(
        corrected=np.full((size, size, 3), 96, dtype=np.uint8),
        annular_roi=np.full((size, size, 3), 96, dtype=np.uint8),
        polar_image=polar,
        raw_inner_boundary=np.full(angles, 6, dtype=np.float32),
        raw_outer_boundary=np.full(angles, 14, dtype=np.float32),
        inner_boundary=np.full(angles, 6, dtype=np.float32),
        outer_boundary=np.full(angles, 14, dtype=np.float32),
        rectification_matrix=np.asarray(
            [[1, 0, 0], [0, 1, 0]], dtype=np.float32
        ),
        corrected_outer_circle=SimpleNamespace(x=16.0, y=16.0),
    )


def _verified_package(root):
    manifest = ModelManifest(
        model_name="multitask",
        model_version="1",
        framework="tensorflow",
        framework_version="2.13.0",
        keras_version="2.13.1",
        python_version="3.11",
        input_spec=ModelInputSpec(
            shape=(2, 2, 3),
            dtype="float32",
            color_space="RGB",
            value_range=(0.0, 1.0),
        ),
        output_names=("cla_out", "seg_out"),
        label_map={0: "qualified", 1: "unqualified"},
        preprocessor=PreprocessorRequirement(
            plugin_id="tool-defect.basic-gray-resize",
            plugin_version="1.0.0",
            config_sha256="sha256:" + "7" * 64,
        ),
        dataset_version="dataset/1",
        source_run_id="run-1",
    )
    return VerifiedModelPackage(
        root=Path(root),
        manifest=manifest,
        package_sha256="8" * 64,
        file_sha256={"environment.lock": "9" * 64},
        signer_key_id="test-key",
        verification_report={"status": "VERIFIED"},
    )


class _FakeKerasLoader:
    def __init__(self):
        self.load_calls = 0
        self.warmup_calls = 0

    def load(self, package, custom_objects):
        self.load_calls += 1
        return _FakeMultitaskModel()

    def warmup(self, model, package):
        self.warmup_calls += 1
        return {"cla_out": (1, 2), "seg_out": (1, 2, 2, 2)}


class _FakeMultitaskModel:
    output_names = ["cla_out", "seg_out"]

    def predict(self, tensor, verbose=0):
        segmentation = np.zeros((1, 2, 2, 2), dtype=np.float32)
        segmentation[..., 0] = 1.0
        return [
            np.asarray([[0.1, 0.9]], dtype=np.float32),
            segmentation,
        ]


if __name__ == "__main__":
    unittest.main()
