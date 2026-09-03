"""Tests for regenerating production visualizations from saved results."""

import csv
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "tools" / "regenerate_multitask_visualizations.py"
SPEC = importlib.util.spec_from_file_location(
    "regenerate_multitask_visualizations",
    SCRIPT_PATH,
)
regenerator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(regenerator)


def _write_png(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise OSError(f"无法写入测试图像：{path}")
    encoded.tofile(str(path))


def _write_predictions(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


class RegenerateVisualizationTests(unittest.TestCase):
    def test_regenerates_saved_raw_result_without_model_loading(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            suite_root = root / "outputs" / "multitask_suite"
            result_dir = suite_root / "raw"
            image_path = root / "processed.png"
            mask_path = result_dir / "masks" / "0000_raw.png"
            _write_png(image_path, np.full((128, 128, 3), 120, dtype=np.uint8))
            mask = np.zeros((128, 128), dtype=np.uint8)
            mask[58:70, 58:70] = 255
            _write_png(mask_path, mask)
            _write_predictions(
                result_dir / "predictions.csv",
                {
                    "sample_id": "qualified/1.png",
                    "image_path": str(image_path),
                    "true_label": "0",
                    "true_class": "qualified",
                    "predicted_label": "1",
                    "predicted_class": "unqualified",
                    "qualified_probability": "0.1",
                    "unqualified_probability": "0.9",
                    "mask_path": "masks/0000_raw.png",
                    "visualization_path": "visualizations/0000_raw_result.png",
                },
            )

            summary = regenerator.regenerate_dataset_visualizations(
                root,
                suite_root,
                "raw",
                "visualizations_clean",
                provenance={},
            )

            output_path = (
                result_dir / "visualizations_clean" / "0000_raw_result.png"
            )
            self.assertEqual(1, summary["generated"])
            self.assertTrue(output_path.is_file())

    def test_boundary_result_uses_cached_geometry_and_circular_background(self):
        from tool_defect.data.ring_geometry import Circle
        from tool_defect.detection.polar_cache import CachedRingResult

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            suite_root = root / "outputs" / "multitask_suite"
            result_dir = suite_root / "boundary_normalized"
            source_path = root / "data" / "images" / "qualified" / "1.png"
            provenance = {"qualified/1.png": {"source_image_path": "images/qualified/1.png"}}
            _write_png(source_path, np.full((64, 64, 3), 120, dtype=np.uint8))
            mask_path = result_dir / "masks" / "0000_boundary.png"
            mask = np.zeros((256, 1440), dtype=np.uint8)
            mask[50:80, :20] = 255
            _write_png(mask_path, mask)
            _write_predictions(
                result_dir / "predictions.csv",
                {
                    "sample_id": "qualified/1.png",
                    "image_path": "unused.png",
                    "true_label": "0",
                    "true_class": "qualified",
                    "predicted_label": "1",
                    "predicted_class": "unqualified",
                    "qualified_probability": "0.1",
                    "unqualified_probability": "0.9",
                    "mask_path": "masks/0000_boundary.png",
                    "visualization_path": "visualizations/0000_boundary_result.png",
                },
            )
            fake_result = CachedRingResult(
                source=np.full((64, 64, 3), 120, dtype=np.uint8),
                corrected=np.empty((512, 512, 3), dtype=np.uint8),
                rectification_matrix=np.asarray(
                    [[8.0, 0.0, 0.0], [0.0, 8.0, 0.0]],
                    dtype=np.float32,
                ),
                corrected_outer_circle=Circle(256.0, 256.0, 235.0),
                polar_image=np.zeros((256, 1440, 3), dtype=np.uint8),
                denoised_polar_image=np.zeros((256, 1440, 3), dtype=np.uint8),
                raw_inner_boundary=np.full(1440, 20.0, dtype=np.float32),
                raw_outer_boundary=np.full(1440, 40.0, dtype=np.float32),
                inner_boundary=np.full(1440, 180.0, dtype=np.float32),
                outer_boundary=np.full(1440, 220.0, dtype=np.float32),
            )
            with mock.patch(
                "tool_defect.detection.polar_cache.load_or_build_cache",
                return_value=(fake_result, "hit"),
            ) as load_cache:
                summary = regenerator.regenerate_dataset_visualizations(
                    root,
                    suite_root,
                    "boundary_normalized",
                    "visualizations_circular",
                    provenance=provenance,
                )

            output_path = (
                result_dir
                / "visualizations_circular"
                / "0000_boundary_result.png"
            )
            self.assertEqual(1, summary["generated"])
            self.assertTrue(output_path.is_file())
            self.assertEqual(1, load_cache.call_count)


if __name__ == "__main__":
    unittest.main()
