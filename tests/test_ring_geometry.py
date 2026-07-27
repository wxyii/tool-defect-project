import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.data.ring_geometry import (
    Circle,
    Ellipse,
    extract_annular_roi,
    locate_circles,
    locate_outer_ellipse,
    process_ring_image,
    rectify_ellipse,
    save_boundary_profiles,
    save_comparison_figure,
    unwrap_annulus,
)


class RingGeometryTests(unittest.TestCase):
    def setUp(self):
        self.image = np.full((420, 520, 3), 25, dtype=np.uint8)
        cv2.circle(self.image, (275, 195), 155, (180, 180, 180), -1)
        cv2.circle(self.image, (275, 195), 72, (20, 20, 20), -1)
        cv2.circle(self.image, (275, 195), 155, (245, 245, 245), 4)
        cv2.circle(self.image, (275, 195), 72, (245, 245, 245), 4)
        for angle in range(0, 360, 15):
            radians = np.deg2rad(angle)
            point = (
                int(round(275 + 115 * np.cos(radians))),
                int(round(195 + 115 * np.sin(radians))),
            )
            cv2.circle(self.image, point, 5, (80, 80, 80), -1)

    def test_locates_inner_and_outer_circle_on_synthetic_ring(self):
        outer, inner = locate_circles(
            self.image,
            outer_radius_scale=1.0,
            inner_radius_scale=1.0,
        )

        self.assertLess(np.hypot(outer.x - 275, outer.y - 195), 8)
        self.assertLess(abs(outer.radius - 155), 8)
        self.assertLess(np.hypot(inner.x - 275, inner.y - 195), 8)
        self.assertLess(abs(inner.radius - 72), 8)

    def test_rectifies_tilted_ellipse_before_unwrapping(self):
        tilted = np.full((420, 520, 3), 25, dtype=np.uint8)
        cv2.ellipse(
            tilted, (275, 195), (155, 85), 25, 0, 360, (180, 180, 180), -1
        )
        cv2.ellipse(
            tilted, (275, 195), (72, 39), 25, 0, 360, (20, 20, 20), -1
        )
        cv2.ellipse(
            tilted, (275, 195), (155, 85), 25, 0, 360, (245, 245, 245), 4
        )
        cv2.ellipse(
            tilted, (275, 195), (72, 39), 25, 0, 360, (245, 245, 245), 4
        )

        ellipse = locate_outer_ellipse(tilted)
        corrected, circle, _ = rectify_ellipse(
            tilted, ellipse, output_size=320
        )
        result = process_ring_image(
            tilted, output_size=320, angle_samples=720
        )

        self.assertLess(abs(ellipse.major_radius - 155), 8)
        self.assertLess(abs(ellipse.minor_radius - 85), 8)
        self.assertLess(abs(ellipse.angle - 25), 5)
        self.assertEqual((320, 320, 3), corrected.shape)
        self.assertAlmostEqual(circle.x, circle.y)
        self.assertEqual(720, result.polar_image.shape[1])
        self.assertLess(float(np.std(result.outer_boundary)), 4.0)

    def test_annular_roi_and_unwrap_have_expected_shapes(self):
        inner = Circle(100, 100, 40)
        outer = Circle(100, 100, 90)
        image = np.full((200, 200, 3), 200, dtype=np.uint8)

        roi = extract_annular_roi(image, inner, outer)
        polar = unwrap_annulus(image, inner, outer, angle_samples=360)

        self.assertTrue(np.all(roi[100, 100] == 0))
        self.assertTrue(np.all(roi[100, 170] == 200))
        self.assertEqual((50, 360, 3), polar.shape)

    def test_complete_pipeline_and_comparison_figure(self):
        result = process_ring_image(
            self.image, output_size=256, angle_samples=360
        )

        self.assertEqual((256, 256, 3), result.corrected.shape)
        self.assertEqual(360, result.polar_image.shape[1])
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "comparison.png"
            save_comparison_figure(
                [result, result], ["类型一", "类型二"], output_path
            )
            profile_path = Path(temp_dir) / "boundaries.csv"
            save_boundary_profiles(result, profile_path)
            self.assertTrue(output_path.is_file())
            self.assertGreater(output_path.stat().st_size, 0)
            self.assertEqual(
                361,
                len(profile_path.read_text(encoding="utf-8").splitlines()),
            )


if __name__ == "__main__":
    unittest.main()
