import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.models.loader import load_saved_model


class SavedModelLoadingTests(unittest.TestCase):
    def test_classification_artifact_loads_with_two_class_output(self):
        """Catches a broken JSON/H5 pair or loading the wrong artifact."""
        model = load_saved_model(PROJECT_ROOT / "artifacts/classification")

        self.assertEqual((None, 299, 299, 3), tuple(model.input_shape))
        self.assertEqual((None, 2), tuple(model.output_shape))

    def test_multitask_artifact_loads_with_classification_and_mask_outputs(self):
        """Catches a broken multitask pair or reversed/incomplete outputs."""
        model = load_saved_model(PROJECT_ROOT / "artifacts/multitask")

        self.assertEqual((None, 256, 256, 3), tuple(model.input_shape))
        self.assertEqual(["cla_out", "seg_out"], model.output_names)
        self.assertEqual((None, 2), tuple(model.output_shape[0]))
        self.assertEqual((None, 256, 256, 2), tuple(model.output_shape[1]))


if __name__ == "__main__":
    unittest.main()
