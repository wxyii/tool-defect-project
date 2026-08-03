from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "worker.py"
spec = importlib.util.spec_from_file_location("r7_worker_tests", PATH)
assert spec is not None and spec.loader is not None
worker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = worker
spec.loader.exec_module(worker)


class Reader:
    def __init__(self, values):
        self.values = values

    def read(self, reference):
        return self.values[reference["object_key"]]


class Writer:
    def put(self, bucket, object_key, media_type, data):
        return {
            "bucket": bucket,
            "object_key": object_key,
            "sha256": worker.sha256_bytes(data),
            "size_bytes": len(data),
            "media_type": media_type,
        }


class SampleExportWorkerTest(unittest.TestCase):
    def setUp(self):
        self.image = b"image"
        self.result = worker.canonical_json({
            "algorithm_outcome": "QUALIFIED",
            "confidence": 0.99,
            "defect_regions": [],
            "model_version": "m/1",
            "pipeline_version": "p/1",
            "rules_version": "r/1",
        })
        self.reader = Reader({"a.png": self.image, "a.json": self.result})

    def reference(self, key, data, media_type):
        return {
            "bucket": "td-raw",
            "object_key": key,
            "sha256": worker.sha256_bytes(data),
            "size_bytes": len(data),
            "media_type": media_type,
        }

    def candidate(self):
        return worker.CandidateInput(
            "019f0000-0000-7000-8000-000000000711",
            {
                "image": self.reference("a.png", self.image, "image/png"),
                "result_reference": self.reference("a.json", self.result, "application/json"),
                "admin_feedback": {"label": "UNCONFIRMED"},
                "detection_updated_at": "2026-08-03T00:00:00Z",
            },
        )

    def test_deterministic_package_contains_manifest_and_hashes(self):
        first = worker.build_package([self.candidate()], self.reader, 1024 * 1024)
        second = worker.build_package([self.candidate()], self.reader, 1024 * 1024)
        self.assertEqual(first.status, "SUCCEEDED")
        self.assertEqual(first.package_bytes, second.package_bytes)
        self.assertIn(b"manifest.json", first.package_bytes)
        self.assertEqual(first.exported_count, 1)

    def test_hash_conflict_is_failed_item(self):
        value = self.candidate()
        snapshot = dict(value.source_snapshot)
        snapshot["image"] = dict(snapshot["image"], sha256="0" * 64)
        result = worker.build_package(
            [worker.CandidateInput(value.candidate_id, snapshot)], self.reader, 1024 * 1024
        )
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(result.items[0].error_code, "OBJECT_HASH_CONFLICT")

    def test_missing_version_is_failed_item_without_default(self):
        value = self.candidate()
        result_bytes = worker.canonical_json({
            "algorithm_outcome": "QUALIFIED", "confidence": 0.99, "defect_regions": []
        })
        snapshot = dict(value.source_snapshot)
        snapshot["result_reference"] = self.reference("a.json", result_bytes, "application/json")
        result = worker.build_package(
            [worker.CandidateInput(value.candidate_id, snapshot)],
            Reader({"a.png": self.image, "a.json": result_bytes}),
            1024 * 1024,
        )
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(result.items[0].error_code, "VERSION_UNAVAILABLE")

    def test_completed_event_contains_package_and_manifest_references(self):
        result = worker.build_package([self.candidate()], self.reader, 1024 * 1024)
        published = worker.publish_export(
            result,
            "sample-exports",
            "sample-exports/job/package.zip",
            "sample-exports/job/manifest.json",
            Writer(),
        )
        event = worker.build_completed_event(
            published,
            message_id="10000000-0000-4000-8000-000000000005",
            job_id="50000000-0000-4000-8000-000000000001",
            occurred_at="2026-08-03T00:04:00Z",
            idempotency_key="idem-sample-completed-1",
            traceparent="00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
        )
        self.assertIn(b'"package"', event)
        self.assertIn(b'"manifest"', event)


if __name__ == "__main__":
    unittest.main()
