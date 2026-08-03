from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/verify-data/verify_data.py"
SPEC = importlib.util.spec_from_file_location("verify_data", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class R2DataVerificationTests(unittest.TestCase):
    def test_r2_data_sources_are_structurally_complete(self) -> None:
        self.assertEqual(MODULE.validate_r2_sources(), [])


if __name__ == "__main__":
    unittest.main()
