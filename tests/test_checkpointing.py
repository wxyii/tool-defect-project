import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

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


if __name__ == "__main__":
    unittest.main()
