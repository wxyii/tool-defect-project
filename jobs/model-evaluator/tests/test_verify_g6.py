"""G6 汇总必须绑定真实存在且哈希一致的逐项门禁结果。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("verify_g6", ROOT / "jobs/model-evaluator/verify_g6.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class G6VerifierTests(unittest.TestCase):
    def test_missing_report_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "missing.json"
            with patch.dict(os.environ, {"G6_REPORT": str(report)}):
                self.assertEqual(2, MODULE.main())

    def test_reference_hash_mismatch_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # 直接调用校验辅助函数时使用真实仓库根；这里验证核心哈希规则，
            # 避免把临时目录伪装成仓库内证据。
            reference = {"path": "jobs/model-evaluator/verify_g6.py", "sha256": "0" * 64}
            errors: list[str] = []
            MODULE.verify_reference(reference, errors, "test")
            self.assertIn("test:sha256_mismatch", errors)
            self.assertTrue(root.is_dir())


if __name__ == "__main__":
    unittest.main()
