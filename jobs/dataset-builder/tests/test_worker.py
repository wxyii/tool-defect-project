#!/usr/bin/env python3
"""数据集构建常驻执行端测试。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


TEST_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TEST_ROOT))

import worker  # noqa: E402


def valid_manifest() -> bytes:
    return (
        "sample_key,content_sha256,split,group_key,label,label_name\n"
        f"normal/one.png,{'a' * 64},train,normal-one,0,qualified\n"
        f"hard/two.png,{'b' * 64},validation,hard-two,1,unqualified\n"
    ).encode("utf-8")


def build_job(payload: bytes, sample_count: int = 2) -> worker.BuildJob:
    return worker.BuildJob(
        dataset_version_id="019f0000-0000-7000-8000-000000000101",
        dataset_id="019f0000-0000-7000-8000-000000000102",
        version="1",
        manifest_bucket="td-datasets",
        manifest_object_key="candidate/production-v1/manifest.csv",
        manifest_sha256=hashlib.sha256(payload).hexdigest(),
        expected_sample_count=sample_count,
    )


class FakeDatabase:
    def __init__(self, job: worker.BuildJob) -> None:
        self.job = job
        self.completed = None
        self.rejected = None
        self.held = None

    def claim(self):
        job, self.job = self.job, None
        return job

    def complete(self, job, result):
        self.completed = (job, result)
        return True

    def reject(self, job, failure):
        self.rejected = (job, failure)
        return True

    def hold(self, job, failure):
        self.held = (job, failure)
        return True


class FakeStorage:
    def __init__(self, payload=None, failure=None) -> None:
        self.payload = payload
        self.failure = failure

    def fetch(self, _bucket, _object_key):
        if self.failure is not None:
            raise self.failure
        return self.payload


class DatasetBuilderWorkerTest(unittest.TestCase):
    def test_valid_manifest_advances_to_validating_with_stratification(self) -> None:
        payload = valid_manifest()
        database = FakeDatabase(build_job(payload))

        outcome = worker.process_one(
            database,
            FakeStorage(payload=payload),
            "dataset-builder-test",
        )

        self.assertEqual("VALIDATING", outcome)
        self.assertIsNotNone(database.completed)
        result = database.completed[1]
        self.assertEqual(2, result.sample_count)
        self.assertEqual(
            {"TRAIN": 1, "VALIDATION": 1},
            result.stratification["split_counts"],
        )
        self.assertEqual("PASSED", result.stratification["builder"]["state"])

    def test_hash_conflict_is_rejected_and_never_completed(self) -> None:
        payload = valid_manifest()
        database = FakeDatabase(build_job(payload))

        outcome = worker.process_one(
            database,
            FakeStorage(payload=payload + b"tampered"),
            "dataset-builder-test",
        )

        self.assertEqual("REJECTED", outcome)
        self.assertIsNone(database.completed)
        self.assertEqual("MANIFEST_HASH_CONFLICT", database.rejected[1].code)

    def test_transient_object_storage_failure_enters_hold(self) -> None:
        payload = valid_manifest()
        database = FakeDatabase(build_job(payload))
        failure = worker.RetryableBuildFailure(
            "OBJECT_STORAGE_UNAVAILABLE",
            "暂时不可达",
        )

        outcome = worker.process_one(
            database,
            FakeStorage(failure=failure),
            "dataset-builder-test",
        )

        self.assertEqual("HOLD", outcome)
        self.assertIsNone(database.completed)
        self.assertIsNone(database.rejected)
        self.assertEqual("OBJECT_STORAGE_UNAVAILABLE", database.held[1].code)

    def test_duplicate_content_and_group_leakage_are_blocked(self) -> None:
        duplicate = (
            "sample_key,content_sha256,split,group_key,label\n"
            f"one.png,{'c' * 64},train,family,0\n"
            f"two.png,{'c' * 64},validation,family,1\n"
        ).encode("utf-8")
        with self.assertRaises(worker.BuildFailure) as caught:
            worker.verify_manifest(
                duplicate,
                build_job(duplicate),
                "dataset-builder-test",
            )
        self.assertEqual("MANIFEST_DUPLICATE_CONTENT", caught.exception.code)

    @mock.patch("worker.subprocess.run")
    def test_database_password_only_uses_stdin(self, run: mock.Mock) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="1\n",
            stderr="",
        )
        database = worker.PsqlDatabase(
            "postgres-container",
            "development-secret",
            "dataset-builder-test",
            30,
        )

        database.health()

        command = run.call_args.args[0]
        self.assertNotIn("development-secret", json.dumps(command))
        self.assertTrue(run.call_args.kwargs["input"].startswith("development-secret\n"))


if __name__ == "__main__":
    unittest.main()
