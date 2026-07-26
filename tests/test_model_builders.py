import sys
import unittest
from pathlib import Path

import tensorflow as tf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.models.classifier import build_classifier
from tool_defect.models.multitask import build_multitask
from tool_defect.models.multitask_agsfpn_reference import (
    build_multitask_agsfpn_reference,
)


class ModelBuilderTests(unittest.TestCase):
    def tearDown(self):
        tf.keras.backend.clear_session()

    def test_classifier_builder_has_source_training_shape_and_two_classes(self):
        """Catches accidental coupling of training architecture to the 299px artifact."""
        model = build_classifier(input_shape=(256, 256, 3), backbone_weights=None)

        self.assertEqual((None, 256, 256, 3), tuple(model.input_shape))
        self.assertEqual((None, 2), tuple(model.output_shape))
        self.assertEqual(["cla_out"], model.output_names)

    def test_default_multitask_builder_has_two_named_outputs(self):
        """Catches removal or renaming of either classification or segmentation head."""
        model = build_multitask(input_shape=(256, 256, 3), backbone_weights=None)

        self.assertEqual(["cla_out", "seg_out"], model.output_names)
        self.assertEqual((None, 2), tuple(model.output_shape[0]))
        self.assertEqual((None, 256, 256, 2), tuple(model.output_shape[1]))

    def test_agsfpn_reference_builder_is_runnable_but_separate(self):
        """Catches the retained AG+FPN reference becoming non-buildable."""
        model = build_multitask_agsfpn_reference(
            input_shape=(256, 256, 3), backbone_weights=None
        )

        self.assertEqual(["cla_out", "seg_out"], model.output_names)
        self.assertEqual((None, 2), tuple(model.output_shape[0]))
        self.assertEqual((None, 256, 256, 2), tuple(model.output_shape[1]))


if __name__ == "__main__":
    unittest.main()
