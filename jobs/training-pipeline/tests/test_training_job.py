#!/usr/bin/env python3
"""P6-03 作业编排的安全失败测试。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

JOB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(JOB_ROOT))

import train  # noqa: E402


class TrainingJobTests(unittest.TestCase):
    def test_resource_pools_must_be_distinct(self) -> None:
        with self.assertRaises(ValueError):
            train.resource_isolation_record("same", "same")
        with patch.dict(os.environ, {"TOOL_DEFECT_RESOURCE_ISOLATION": ""}):
            record = train.resource_isolation_record("train-a", "infer-b")
        self.assertEqual("DECLARED", record["status"])
        self.assertTrue(record["exclusive"])

    def test_missing_dataset_version_and_model_create_blocked_run_without_training(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p6-03-preflight-") as temp:
            root = Path(temp)
            config = root / "config.json"
            config.write_text(
                json.dumps({
                    "image_size": 8,
                    "seed": 7,
                    "paths": {
                        "data": "data",
                        "manifest": "data/manifest.csv",
                        "multitask_model": "artifacts/multitask",
                    },
                }),
                encoding="utf-8",
            )
            output = root / "controlled-output"
            code, result = train.execute_training(
                config_path=config,
                output_root=output,
                run_id="blocked-preflight",
                dataset_version=None,
                init_model_dir=None,
                smoke=True,
                resume=None,
                training_pool="ml-training",
                inference_pool="ml-inference",
            )
            self.assertEqual(1, code)
            self.assertEqual("BLOCKED", result["status"])
            self.assertTrue((output / "blocked-preflight" / "job-provenance.json").is_file())
            self.assertFalse((output / "blocked-preflight" / "weights.h5").exists())
            self.assertTrue(any("dataset_version_missing" in item for item in result["reproducibility_details"]))

    def test_existing_run_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p6-03-immutable-") as temp:
            root = Path(temp)
            output = root / "controlled-output"
            run_dir = output / "existing"
            run_dir.mkdir(parents=True)
            sentinel = run_dir / "sentinel"
            sentinel.write_text("keep", encoding="utf-8")
            code, result = train.execute_training(
                config_path=root / "missing.json",
                output_root=output,
                run_id="existing",
                dataset_version=None,
                init_model_dir=None,
                smoke=True,
                resume=None,
                training_pool="ml-training",
                inference_pool="ml-inference",
            )
            self.assertEqual(2, code)
            self.assertEqual("BLOCKED", result["status"])
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))

    def test_verifier_rejects_old_pseudo_run(self) -> None:
        old_run = train.REPO_ROOT / "jobs" / "training-pipeline" / "controlled-output" / "train-1785480945"
        if not old_run.is_dir():
            self.skipTest("历史受控输出不存在")
        result = __import__("verify_p6_03").verify_run(old_run)
        self.assertEqual("BLOCKED", result["status"])
        self.assertGreater(result["error_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
