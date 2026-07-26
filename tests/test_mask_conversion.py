import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.data.mask_conversion import convert_annotation


class MaskConversionTests(unittest.TestCase):
    def test_labelme_polygon_converts_to_binary_png(self):
        """Catches loss of the supplied Labelme-to-mask utility."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            annotation = root / "sample.json"
            destination = root / "sample.png"
            annotation.write_text(
                json.dumps(
                    {
                        "imageHeight": 10,
                        "imageWidth": 10,
                        "shapes": [
                            {
                                "points": [[2, 2], [7, 2], [7, 7], [2, 7]],
                                "label": "defect",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            convert_annotation(annotation, destination)

            mask = cv2.imdecode(
                np.fromfile(destination, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
            )
            self.assertEqual((10, 10), mask.shape)
            self.assertEqual({0, 255}, set(np.unique(mask)))


if __name__ == "__main__":
    unittest.main()
