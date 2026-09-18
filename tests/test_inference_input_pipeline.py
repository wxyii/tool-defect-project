import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.inference.input_pipeline import (
    BOUNDARY_NORMALIZED_8PATCH_INPUT,
    BOUNDARY_NORMALIZED_INPUT,
    RAW_INPUT,
    _as_patch_parent_probability,
    aggregate_class_probabilities,
    load_ring_settings,
    prepare_input_batch,
    resolve_input_mode,
    restore_defect_mask,
)


def _fake_ring_result():
    source = np.zeros((20, 20, 3), dtype=np.uint8)
    return SimpleNamespace(
        source=source,
        corrected=source.copy(),
        rectification_matrix=np.asarray(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            dtype=np.float32,
        ),
        corrected_outer_circle=SimpleNamespace(x=10.0, y=10.0),
        inner_boundary=np.full(16, 3.0, dtype=np.float32),
        outer_boundary=np.full(16, 9.0, dtype=np.float32),
        outer_ellipse=SimpleNamespace(
            x=10.0,
            y=10.0,
            major_radius=9.0,
            minor_radius=9.0,
            angle=0.0,
        ),
        inner_ellipse=SimpleNamespace(
            x=10.0,
            y=10.0,
            major_radius=3.0,
            minor_radius=3.0,
            angle=0.0,
        ),
    )


class InferenceInputPipelineTests(unittest.TestCase):
    def test_auto_mode_follows_selected_dataset_config(self):
        self.assertEqual(
            BOUNDARY_NORMALIZED_INPUT,
            resolve_input_mode(
                "auto", Path("data/processed/boundary_normalized")
            ),
        )
        self.assertEqual(
            BOUNDARY_NORMALIZED_8PATCH_INPUT,
            resolve_input_mode(
                "auto", Path("data/processed/boundary_normalized_8patch")
            ),
        )
        self.assertEqual(RAW_INPUT, resolve_input_mode("auto", Path("data")))

    def test_ring_settings_match_saved_generation_reports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            full_root = root / "boundary_normalized"
            patch_root = root / "boundary_normalized_8patch"
            full_root.mkdir()
            patch_root.mkdir()
            (full_root / "generation_report.json").write_text(
                json.dumps(
                    {
                        "status": "complete",
                        "output_size": 512,
                        "angle_samples": 1440,
                        "radial_samples": 256,
                    }
                ),
                encoding="utf-8",
            )
            (patch_root / "generation_report.json").write_text(
                json.dumps(
                    {
                        "status": "complete",
                        "slice_count": 8,
                        "window_degrees": 90,
                        "stride_degrees": 45,
                    }
                ),
                encoding="utf-8",
            )

            full = load_ring_settings(full_root, BOUNDARY_NORMALIZED_INPUT)
            patches = load_ring_settings(
                patch_root,
                BOUNDARY_NORMALIZED_8PATCH_INPUT,
            )

        self.assertEqual(512, full["output_size"])
        self.assertEqual(256, full["radial_samples"])
        self.assertEqual(1440, full["angle_samples"])
        self.assertEqual(8, patches["slice_count"])
        self.assertEqual(90.0, patches["window_degrees"])
        self.assertEqual(45.0, patches["stride_degrees"])

    @mock.patch("tool_defect.inference.input_pipeline.normalize_boundary_image")
    @mock.patch("tool_defect.inference.input_pipeline.process_image_path")
    def test_full_and_patch_batches_follow_training_shapes(
        self,
        process_image_path,
        normalize_boundary_image,
    ):
        ring_result = _fake_ring_result()
        normalized = np.zeros((8, 16, 3), dtype=np.uint8)
        normalized[:, :, 0] = np.arange(16, dtype=np.uint8)[None, :]
        process_image_path.return_value = ring_result
        normalize_boundary_image.return_value = normalized
        settings = {
            "output_size": 20,
            "angle_samples": 16,
            "radial_samples": 8,
            "slice_count": 8,
            "window_degrees": 90,
            "stride_degrees": 45,
        }

        full_batch, full_context = prepare_input_batch(
            "blade.png",
            4,
            BOUNDARY_NORMALIZED_INPUT,
            settings,
        )
        patch_batch, patch_context = prepare_input_batch(
            "blade.png",
            4,
            BOUNDARY_NORMALIZED_8PATCH_INPUT,
            settings,
        )

        self.assertEqual((1, 4, 4, 3), full_batch.shape)
        self.assertEqual((8, 4, 4, 3), patch_batch.shape)
        self.assertEqual(BOUNDARY_NORMALIZED_INPUT, full_context.mode)
        self.assertEqual(BOUNDARY_NORMALIZED_8PATCH_INPUT, patch_context.mode)
        self.assertEqual(2, process_image_path.call_count)
        self.assertEqual(2, normalize_boundary_image.call_count)

    def test_patch_classification_aggregates_to_parent_using_max_bad_probability(self):
        _, context = self._prepared_patch_context()
        probabilities = np.tile([0.9, 0.1], (8, 1)).astype(np.float32)
        probabilities[5] = [0.2, 0.8]

        parent = aggregate_class_probabilities(probabilities, context)

        np.testing.assert_allclose([0.2, 0.8], parent)

    def test_patch_segmentation_fusion_wraps_across_angular_seam(self):
        _, context = self._prepared_patch_context()
        segmentation = np.zeros((8, 2, 2, 2), dtype=np.float32)
        segmentation[7, ..., 1] = 1.0

        parent_probability = _as_patch_parent_probability(
            segmentation,
            context,
        )

        np.testing.assert_allclose(
            np.ones((8, 4), dtype=np.float32),
            parent_probability[:, [14, 15, 0, 1]],
        )
        self.assertEqual(0.0, float(parent_probability[:, 2:14].max()))

    def test_full_and_patch_masks_map_back_to_original_image_coordinates(self):
        _, full_context = self._prepared_full_context()
        full_segmentation = np.zeros((1, 4, 4, 2), dtype=np.float32)
        full_segmentation[..., 1] = 1.0
        full_mask = restore_defect_mask(full_segmentation, full_context)
        self.assertEqual((20, 20), full_mask.shape)
        self.assertEqual(0, int(full_mask[10, 10]))
        self.assertEqual(255, int(full_mask[10, 15]))

        _, patch_context = self._prepared_patch_context()
        patch_segmentation = np.zeros((8, 4, 4, 2), dtype=np.float32)
        patch_segmentation[..., 1] = 1.0
        patch_mask = restore_defect_mask(patch_segmentation, patch_context)
        self.assertEqual((20, 20), patch_mask.shape)
        self.assertEqual(0, int(patch_mask[10, 10]))
        self.assertEqual(255, int(patch_mask[10, 15]))

    def _prepared_full_context(self):
        with mock.patch(
            "tool_defect.inference.input_pipeline.process_image_path",
            return_value=_fake_ring_result(),
        ), mock.patch(
            "tool_defect.inference.input_pipeline.normalize_boundary_image",
            return_value=np.zeros((8, 16, 3), dtype=np.uint8),
        ):
            return prepare_input_batch(
                "blade.png",
                4,
                BOUNDARY_NORMALIZED_INPUT,
                {
                    "output_size": 20,
                    "angle_samples": 16,
                    "radial_samples": 8,
                },
            )

    def _prepared_patch_context(self):
        with mock.patch(
            "tool_defect.inference.input_pipeline.process_image_path",
            return_value=_fake_ring_result(),
        ), mock.patch(
            "tool_defect.inference.input_pipeline.normalize_boundary_image",
            return_value=np.zeros((8, 16, 3), dtype=np.uint8),
        ):
            return prepare_input_batch(
                "blade.png",
                4,
                BOUNDARY_NORMALIZED_8PATCH_INPUT,
                {
                    "output_size": 20,
                    "angle_samples": 16,
                    "radial_samples": 8,
                    "slice_count": 8,
                    "window_degrees": 90,
                    "stride_degrees": 45,
                },
            )


if __name__ == "__main__":
    unittest.main()
