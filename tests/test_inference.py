import csv
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.inference.predict import predict


class InferenceTests(unittest.TestCase):
    def test_supplied_classification_weights_predict_one_real_image(self):
        """Catches preprocessing/model loading mismatches in classification inference."""
        image = next((PROJECT_ROOT / "data/images/qualified").iterdir())
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result_path = predict(
                task="classification",
                input_paths=image,
                output_dir=output_dir,
                model_dir=PROJECT_ROOT / "artifacts/classification",
            )

            with result_path.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(1, len(rows))
            self.assertIn(rows[0]["predicted_class"], {"qualified", "unqualified"})
            self.assertAlmostEqual(
                1.0,
                float(rows[0]["qualified_probability"])
                + float(rows[0]["unqualified_probability"]),
                places=4,
            )

    def test_supplied_multitask_weights_write_classification_and_mask(self):
        """Catches reversed outputs or failure to materialize the predicted mask."""
        image = next((PROJECT_ROOT / "data/images/unqualified").iterdir())
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            result_path = predict(
                task="multitask",
                input_paths=image,
                output_dir=output_dir,
                model_dir=PROJECT_ROOT / "artifacts/multitask",
            )

            with result_path.open(newline="", encoding="utf-8-sig") as handle:
                row = next(csv.DictReader(handle))
            mask_path = output_dir / row["mask_path"]
            self.assertTrue(mask_path.is_file())
            self.assertGreater(mask_path.stat().st_size, 0)
            visualization_path = output_dir / row["visualization_path"]
            self.assertTrue(visualization_path.is_file())
            self.assertTrue(visualization_path.name.endswith("_result.png"))
            encoded = np.fromfile(str(visualization_path), dtype=np.uint8)
            rendered = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            self.assertIsNotNone(rendered)
            self.assertLessEqual(max(rendered.shape[:2]), 1600)


if __name__ == "__main__":
    unittest.main()
