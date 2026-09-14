import sys
import unittest
from pathlib import Path

import numpy as np
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tool_defect.training.checkpointing import ParentClassificationMetricsCallback
from tool_defect.training.checkpointing import parent_id_from_row


class CheckpointingTests(unittest.TestCase):
    def test_patch_parent_id_ignores_child_label_directory(self):
        qualified_patch = {
            "sample_id": "qualified/unqualified__100__patch_00.png"
        }
        unqualified_patch = {
            "sample_id": "unqualified/unqualified__100__patch_01.png"
        }
        self.assertEqual(
            parent_id_from_row(qualified_patch),
            parent_id_from_row(unqualified_patch),
        )
        self.assertEqual(
            "unqualified__100",
            parent_id_from_row(qualified_patch),
        )

    def test_explicit_parent_id_remains_authoritative(self):
        row = {
            "sample_id": "qualified/unqualified__100__patch_00.png",
            "parent_sample_id": "source/unqualified/100.png",
        }
        self.assertEqual("source/unqualified/100.png", parent_id_from_row(row))

    def test_parent_callback_uses_parent_labels_for_mixed_patch_labels(self):
        rows = [
            {
                "sample_id": "unqualified/unqualified__12__patch_00.png",
                "label": "1",
            },
            {
                "sample_id": "qualified/unqualified__12__patch_01.png",
                "label": "0",
            },
        ]
        model = mock.Mock()
        model.output_names = ["cla_out"]
        model.predict.return_value = np.asarray(
            [[0.1, 0.9], [0.9, 0.1]], dtype=np.float32
        )
        callback = ParentClassificationMetricsCallback(
            object(),
            rows,
            validation_parent_labels=[1, 1],
        )
        callback.set_model(model)

        logs = {}
        callback.on_epoch_end(0, logs)

        self.assertEqual(1.0, logs["val_parent_unqualified_recall"])


if __name__ == "__main__":
    unittest.main()
