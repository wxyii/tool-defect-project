from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools/verify-layout/strict_unittest.py"


class StrictUnittestRunnerTests(unittest.TestCase):
    def _run(self, source: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="strict-unittest-") as temporary:
            root = Path(temporary)
            (root / "test_sample.py").write_text(source, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(RUNNER), str(root)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

    def test_plain_success_returns_zero(self):
        result = self._run(
            "import unittest\n"
            "class Sample(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertTrue(True)\n"
        )
        self.assertEqual(0, result.returncode, result.stdout)

    def test_skip_returns_two_and_reports_reason(self):
        result = self._run(
            "import unittest\n"
            "class Sample(unittest.TestCase):\n"
            "    def test_missing_prerequisite(self):\n"
            "        self.skipTest('missing-prerequisite')\n"
        )
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("missing-prerequisite", result.stdout)
        self.assertIn("严格测试失败", result.stdout)

    def test_expected_failure_returns_two(self):
        result = self._run(
            "import unittest\n"
            "class Sample(unittest.TestCase):\n"
            "    @unittest.expectedFailure\n"
            "    def test_not_done(self):\n"
            "        self.fail('not-done')\n"
        )
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("预期失败", result.stdout)


if __name__ == "__main__":
    unittest.main()
