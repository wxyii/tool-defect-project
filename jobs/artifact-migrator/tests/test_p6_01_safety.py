"""P6-01 新增安全门禁的快速单元测试。"""

import tempfile
import unittest
from pathlib import Path
import sys


MODULE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE_ROOT))

import migrate
from register_objects import safe_key
from verify_p6_01 import rel_path


class P601SafetyTests(unittest.TestCase):
    def test_source_path_cannot_escape_data_root(self):
        data_root = Path("/tmp/p6-data-root")
        self.assertIsNone(rel_path("../outside.bin", data_root))
        self.assertIsNone(rel_path("/absolute.bin", data_root))
        self.assertEqual(rel_path("images/sample.bin", data_root), (data_root / "images/sample.bin").resolve())

    def test_object_key_cannot_contain_traversal(self):
        with self.assertRaises(ValueError):
            safe_key("datasets", "../outside")
        with self.assertRaises(ValueError):
            safe_key("", "object")

    def test_migrator_refuses_to_overwrite_nonempty_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "controlled-output"
            output_dir.mkdir()
            marker = output_dir / "immutable-marker.txt"
            marker.write_text("keep", encoding="utf-8")
            result = migrate.main(["--output-dir", str(output_dir)])
            self.assertEqual(result, 2)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
