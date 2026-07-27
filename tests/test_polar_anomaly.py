import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.detection.polar_anomaly import (
    DetectionResult,
    MODEL_VERSION,
    PolarAnomalyModel,
    _regions_from_map,
    _robust_location_scale,
    _sample_feature_tuples,
    analyze_ring_result,
    detect_ring_result,
    estimate_period_count,
    iter_image_paths,
    save_detection_artifacts,
)
from tool_defect.detection.polar_cache import (
    cache_entry_is_valid,
    load_cache_entry,
    load_or_build_cache,
    save_cache_entry,
)
from tool_defect.detection.polar_preprocess import denoise_polar_image
from tool_defect.data.ring_geometry import Circle


def _periodic_polar(period_count=24, phase=0, brightness=0):
    height, width = 84, 720
    x = np.arange(width, dtype=np.float32)
    y = np.arange(height, dtype=np.float32)[:, None]
    angle = 2.0 * np.pi * period_count * (x - phase) / width
    motif = (
        34.0 * np.cos(angle)[None, :] * np.exp(-((y - 28.0) / 15.0) ** 2)
        + 15.0 * np.sin(2.0 * angle)[None, :]
        + 8.0 * np.cos(angle + y / 18.0)
    )
    gray = np.clip(115.0 + brightness + motif, 0.0, 255.0).astype(np.uint8)
    return np.repeat(gray[:, :, None], 3, axis=2)


def _ring_stub(polar_image, edge_defect=None):
    width = polar_image.shape[1]
    outer = np.full(width, 240.0, dtype=np.float32)
    raw = outer.copy()
    if edge_defect is not None:
        start, stop, depth = edge_defect
        indices = np.arange(start, stop) % width
        raw[indices] -= depth
    return SimpleNamespace(
        polar_image=polar_image,
        raw_outer_boundary=raw,
        outer_boundary=outer,
    )


def _calibrated_model(clean_analyses):
    samples = np.concatenate(
        [_sample_feature_tuples(item.feature_maps) for item in clean_analyses],
        axis=0,
    )
    centers = []
    scales = []
    for index in range(3):
        center, scale = _robust_location_scale(samples[:, index])
        centers.append(center)
        scales.append(scale)
    return PolarAnomalyModel(
        version=MODEL_VERSION,
        feature_centers=tuple(centers),
        feature_scales=tuple(scales),
        threshold=4.0,
        output_size=512,
        angle_samples=720,
        minimum_periods=8,
        maximum_periods=40,
        calibration_images=len(clean_analyses),
    )


class PolarAnomalyTests(unittest.TestCase):
    def test_polar_denoising_reduces_noise_and_keeps_shape(self):
        clean = _periodic_polar(24)
        generator = np.random.default_rng(7)
        noisy = np.clip(
            clean.astype(np.int16)
            + generator.normal(0.0, 18.0, clean.shape),
            0,
            255,
        ).astype(np.uint8)

        denoised = denoise_polar_image(noisy)

        self.assertEqual(noisy.shape, denoised.shape)
        self.assertEqual(np.uint8, denoised.dtype)
        noisy_error = np.mean(
            np.abs(noisy.astype(np.float32) - clean.astype(np.float32))
        )
        denoised_error = np.mean(
            np.abs(denoised.astype(np.float32) - clean.astype(np.float32))
        )
        self.assertLess(denoised_error, noisy_error * 0.75)

    def test_estimates_different_period_counts_and_ignores_phase(self):
        for count, phase in ((18, 0), (24, 11), (30, 7)):
            polar = _periodic_polar(count, phase=phase)
            gray = cv2.cvtColor(polar, cv2.COLOR_BGR2GRAY).astype(np.float32)
            gray -= np.mean(gray, axis=1, keepdims=True)
            self.assertEqual(count, estimate_period_count(gray))

    def test_texture_and_outer_edge_anomalies_score_above_clean_image(self):
        clean_rings = [
            _ring_stub(_periodic_polar(24, phase=phase, brightness=brightness))
            for phase, brightness in ((0, 0), (5, 18), (13, -15))
        ]
        clean_analyses = [analyze_ring_result(ring) for ring in clean_rings]
        model = _calibrated_model(clean_analyses)
        _, _, _, clean_regions, clean_score = detect_ring_result(
            clean_rings[0], model
        )

        defective = _periodic_polar(24, phase=4)
        defective[20:48, 194:216] = (245, 245, 245)
        defective_ring = _ring_stub(
            defective, edge_defect=(690, 714, 13.0)
        )
        _, _, _, defect_regions, defect_score = detect_ring_result(
            defective_ring, model
        )

        self.assertGreater(defect_score, clean_score + 2.0)
        self.assertTrue(defect_regions)
        self.assertGreaterEqual(defect_score, model.threshold)
        self.assertLessEqual(len(clean_regions), len(defect_regions))

    def test_regions_merge_across_zero_degree_seam(self):
        score = np.zeros((40, 120), dtype=np.float32)
        score[5:15, :7] = 8.0
        score[5:15, -8:] = 8.0

        mask, regions = _regions_from_map(score, threshold=4.0)

        self.assertEqual(1, len(regions))
        self.assertEqual(150, int(np.sum(mask)))
        self.assertGreater(
            regions[0].start_angle_degrees,
            regions[0].end_angle_degrees,
        )

    def test_model_round_trip_and_image_discovery_do_not_use_labels(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for directory in ("任意目录甲", "任意目录乙/更深层"):
                (root / directory).mkdir(parents=True)
            (root / "任意目录甲/a.png").write_bytes(b"one")
            (root / "任意目录乙/更深层/b.jpg").write_bytes(b"two")
            (root / "任意目录乙/说明.txt").write_text("ignore", encoding="utf-8")

            paths = iter_image_paths(root)
            self.assertEqual(
                ["a.png", "b.jpg"], sorted(path.name for path in paths)
            )

            model = PolarAnomalyModel(
                version=MODEL_VERSION,
                feature_centers=(1.0, 2.0, 3.0),
                feature_scales=(0.5, 0.6, 0.7),
                threshold=4.5,
                calibration_images=12,
            )
            model_path = model.save(root / "model")
            loaded = PolarAnomalyModel.load(model_path.parent)
            self.assertEqual(model, loaded)
            payload = json.loads(model_path.read_text(encoding="utf-8"))
            self.assertNotIn("class_names", payload)
            self.assertNotIn("labels", payload)

    def test_visualizations_are_written_and_mapped_back_to_source(self):
        height, width = 40, 120
        candidate = np.zeros((height, width), dtype=np.uint8)
        candidate[2:10, 25:34] = 1
        source = np.full((160, 160, 3), 90, dtype=np.uint8)
        ring = SimpleNamespace(
            polar_image=np.full((height, width, 3), 110, dtype=np.uint8),
            corrected=source.copy(),
            source=source,
            inner_boundary=np.full(width, 35.0, dtype=np.float32),
            outer_boundary=np.full(width, 70.0, dtype=np.float32),
            corrected_outer_circle=Circle(80.0, 80.0, 70.0),
            rectification_matrix=np.array(
                [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32
            ),
        )
        result = DetectionResult(
            image_path=Path("synthetic.png"),
            status="ok",
            message="",
            anomaly_score=9.0,
            threshold=6.0,
            period_count=20,
            phase_offset=0,
            regions=[],
            ring_result=ring,
            anomaly_map=candidate.astype(np.float32) * 9.0,
            candidate_mask=candidate,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            paths = save_detection_artifacts(result, temp_dir, "synthetic")

            self.assertEqual(
                {"heatmap", "polar_overlay", "source_overlay"}, set(paths)
            )
            for path in paths.values():
                self.assertTrue(Path(path).is_file())
                self.assertGreater(Path(path).stat().st_size, 0)
            mapped = cv2.imdecode(
                np.fromfile(paths["source_overlay"], dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            self.assertGreater(int(np.sum(mapped[:, :, 2] > mapped[:, :, 1])), 0)

    def test_polar_cache_round_trip_and_source_invalidation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "nested" / "input.png"
            source_path.parent.mkdir()
            source = np.full((64, 64, 3), 80, dtype=np.uint8)
            success, encoded = cv2.imencode(".png", source)
            self.assertTrue(success)
            encoded.tofile(str(source_path))
            width = 120
            ring = SimpleNamespace(
                source=source,
                corrected=np.full((80, 80, 3), 70, dtype=np.uint8),
                polar_image=_periodic_polar(20)[:, :width],
                raw_inner_boundary=np.full(width, 25.0, dtype=np.float32),
                raw_outer_boundary=np.full(width, 55.0, dtype=np.float32),
                inner_boundary=np.full(width, 26.0, dtype=np.float32),
                outer_boundary=np.full(width, 54.0, dtype=np.float32),
                rectification_matrix=np.array(
                    [[1.0, 0.0, 4.0], [0.0, 1.0, 5.0]],
                    dtype=np.float32,
                ),
                corrected_outer_circle=Circle(40.0, 40.0, 35.0),
            )
            cache_dir = root / "cache"
            entry_dir = save_cache_entry(
                source_path,
                root,
                cache_dir,
                ring,
                output_size=80,
                angle_samples=width,
            )

            self.assertTrue(
                cache_entry_is_valid(
                    source_path,
                    root,
                    entry_dir,
                    output_size=80,
                    angle_samples=width,
                )
            )
            self.assertTrue((entry_dir / "polar_denoised.png").is_file())
            loaded = load_cache_entry(
                source_path, root, cache_dir, load_source=True
            )
            np.testing.assert_array_equal(ring.polar_image, loaded.polar_image)
            self.assertEqual(
                ring.polar_image.shape,
                loaded.denoised_polar_image.shape,
            )
            np.testing.assert_allclose(
                ring.outer_boundary, loaded.outer_boundary
            )
            np.testing.assert_allclose(
                ring.rectification_matrix, loaded.rectification_matrix
            )
            self.assertEqual(source.shape, loaded.source.shape)

            _, cache_state = load_or_build_cache(
                source_path,
                source_path.parent,
                cache_dir,
                output_size=80,
                angle_samples=width,
                load_source=False,
            )
            self.assertEqual("hit", cache_state)
            self.assertEqual(1, len(list(cache_dir.glob("*/geometry.npz"))))

            changed = source.copy()
            changed[0, 0] = 255
            success, encoded = cv2.imencode(".png", changed)
            self.assertTrue(success)
            encoded.tofile(str(source_path))
            self.assertFalse(
                cache_entry_is_valid(
                    source_path,
                    root,
                    entry_dir,
                    output_size=80,
                    angle_samples=width,
                )
            )


if __name__ == "__main__":
    unittest.main()
