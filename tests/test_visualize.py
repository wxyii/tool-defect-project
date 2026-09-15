"""Tests for truthful, readable defect visualization."""

import inspect
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from tool_defect.inference import visualize


def _write_image(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(path.suffix or ".png", image)
    if not success:
        raise OSError(f"unable to encode test image: {path}")
    encoded.tofile(path)


def _read_image(path):
    encoded = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise OSError(f"unable to decode test image: {path}")
    return image


class VisualizationTests(unittest.TestCase):
    def test_large_image_is_resized_and_marks_defect_without_mutating_mask(self):
        """Catches full-resolution output, hidden defects, or in-place mask edits."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "original.png"
            output_path = root / "result.png"
            image = np.full((1000, 2000, 3), 150, dtype=np.uint8)
            mask = np.zeros((256, 256), dtype=np.uint8)
            mask[80:120, 160:200] = 255
            original_mask = mask.copy()
            _write_image(image_path, image)

            visualize.overlay_defect_on_image(
                original_path=image_path,
                defect_mask=mask,
                predicted_class="unqualified",
                confidence=0.9,
                output_path=output_path,
            )

            rendered = _read_image(output_path)
            self.assertLessEqual(max(rendered.shape[:2]), 1600)
            np.testing.assert_array_equal(mask, original_mask)
            red_pixels = (
                (rendered[..., 2].astype(np.int16) - rendered[..., 1] > 40)
                & (rendered[..., 2].astype(np.int16) - rendered[..., 0] > 40)
            )
            self.assertGreater(int(red_pixels.sum()), 1000)

    def test_status_messages_distinguish_location_and_review_cases(self):
        """Catches misleading Chinese text when location evidence is absent."""
        self.assertTrue(
            hasattr(visualize, "build_visualization_status"),
            "build_visualization_status is required",
        )
        located = visualize.build_visualization_status(
            "unqualified", 0.9123, raw_has_defect=True, component_count=2
        )
        missing = visualize.build_visualization_status(
            "unqualified", 0.8, raw_has_defect=False, component_count=0
        )
        conflict = visualize.build_visualization_status(
            "qualified", 0.7, raw_has_defect=True, component_count=1
        )
        clean = visualize.build_visualization_status(
            "qualified", 0.95, raw_has_defect=False, component_count=0
        )

        self.assertIn("检测结果：不合格", located.text)
        self.assertIn("分类置信度：91.23%", located.text)
        self.assertIn("检测到 2 处疑似缺陷", located.text)
        self.assertIn("未能定位缺陷区域，请人工复核", missing.text)
        self.assertIn("分类与定位结果不一致，请人工复核", conflict.text)
        self.assertIn("未检测到缺陷区域", clean.text)

    def test_tiny_components_are_filtered_only_from_display_mask(self):
        """Catches isolated prediction noise being presented as a clear defect."""
        self.assertTrue(
            hasattr(visualize, "filter_display_components"),
            "filter_display_components is required",
        )
        mask = np.zeros((256, 256), dtype=np.uint8)
        mask[10, 10] = 255
        mask[100:104, 120:124] = 255
        original_mask = mask.copy()

        filtered, components = visualize.filter_display_components(
            mask, min_component_area=12
        )

        np.testing.assert_array_equal(mask, original_mask)
        self.assertEqual(0, int(filtered[10, 10]))
        self.assertEqual(255, int(filtered[101, 121]))
        self.assertEqual(1, len(components))

    def test_zero_overlay_alpha_keeps_outline_without_coloring_defect_fill(self):
        """Catches custom alpha being applied after and erasing defect outlines."""
        parameters = inspect.signature(visualize._mark_components).parameters
        self.assertIn("overlay_alpha", parameters)
        image = np.full((256, 256, 3), 100, dtype=np.uint8)
        mask = np.zeros((256, 256), dtype=np.uint8)
        mask[80:176, 80:176] = 255
        filtered, components = visualize.filter_display_components(mask)

        transparent = visualize._mark_components(
            image,
            filtered,
            components,
            source_shape=mask.shape,
            overlay_alpha=0.0,
        )
        opaque = visualize._mark_components(
            image,
            filtered,
            components,
            source_shape=mask.shape,
            overlay_alpha=1.0,
        )

        np.testing.assert_array_equal(transparent[128, 128], [100, 100, 100])
        self.assertGreater(int(transparent[128, 80, 2]), 200)
        self.assertGreater(int(opaque[128, 128, 2]), 240)
        self.assertLess(int(opaque[128, 128, 1]), 20)

    def test_chinese_paths_work_and_missing_font_has_clear_error(self):
        """Catches Windows Chinese-path failures or silently garbled text."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "中文目录"
            image_path = root / "刀具.png"
            output_path = root / "检测结果.png"
            image = np.full((300, 300, 3), 120, dtype=np.uint8)
            mask = np.zeros((256, 256), dtype=np.uint8)
            _write_image(image_path, image)

            result = visualize.overlay_defect_on_image(
                original_path=image_path,
                defect_mask=mask,
                predicted_class="qualified",
                confidence=0.95,
                output_path=output_path,
            )

            self.assertEqual(output_path, result)
            rendered = _read_image(output_path)
            self.assertGreater(rendered.shape[0], image.shape[0])
            self.assertGreater(int(np.count_nonzero(rendered[:80])), 0)

            with self.assertRaisesRegex(FileNotFoundError, "中文字体"):
                visualize.overlay_defect_on_image(
                    original_path=image_path,
                    defect_mask=mask,
                    predicted_class="qualified",
                    confidence=0.95,
                    output_path=root / "字体失败.png",
                    font_path=root / "不存在.ttf",
                )


if __name__ == "__main__":
    unittest.main()
