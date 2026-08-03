#!/usr/bin/env python3
"""R7-07 离线正负样例门禁。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = Path(__file__).resolve().parent / "worker.py"
spec = importlib.util.spec_from_file_location("r7_sample_export_worker", WORKER_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("无法加载 R7 worker")
worker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = worker
spec.loader.exec_module(worker)


class MemoryReader:
    def __init__(self, values: dict[str, bytes]) -> None:
        self.values = values

    def read(self, reference):
        return self.values[reference["object_key"]]


class MemoryWriter:
    def put(self, bucket, object_key, media_type, data):
        return {
            "bucket": bucket,
            "object_key": object_key,
            "sha256": worker.sha256_bytes(data),
            "size_bytes": len(data),
            "media_type": media_type,
        }


def ref(key: str, data: bytes, media_type: str) -> dict[str, object]:
    return {
        "bucket": "td-raw",
        "object_key": key,
        "sha256": worker.sha256_bytes(data),
        "size_bytes": len(data),
        "media_type": media_type,
    }


def candidate(candidate_id: str, image_key: str, image: bytes, result_key: str, result: bytes):
    return worker.CandidateInput(
        candidate_id,
        {
            "image": ref(image_key, image, "image/png"),
            "result_reference": ref(result_key, result, "application/json"),
            "admin_feedback": {"label": "FALSE_POSITIVE"},
            "employee_feedback": {"decision": "DEFECT_CONFIRMED"},
            "detection_updated_at": "2026-08-03T00:00:00Z",
        },
    )


def main() -> int:
    image = b"PNG-R7-SAMPLE"
    result = worker.canonical_json(
        {
            "algorithm_outcome": "UNQUALIFIED",
            "confidence": 0.92,
            "defect_regions": [{"geometry_type": "BOX", "x": 1, "y": 2}],
            "model_version": "model/r7-1",
            "pipeline_version": "pipeline/r7-1",
            "rules_version": "rules/r7-1",
        }
    )
    first = candidate("019f0000-0000-7000-8000-000000000701", "a.png", image, "a.json", result)
    second = candidate("019f0000-0000-7000-8000-000000000702", "b.png", image, "b.json", result)
    reader = MemoryReader({"a.png": image, "b.png": image, "a.json": result, "b.json": result})

    positive = worker.build_package([first], reader, 1024 * 1024)
    repeat = worker.build_package([first], reader, 1024 * 1024)
    assert positive.status == "SUCCEEDED"
    assert positive.failed_count == 0
    assert positive.package_bytes == repeat.package_bytes
    assert b"manifest.json" in positive.package_bytes

    published = worker.publish_export(
        positive,
        "sample-exports",
        "sample-exports/job/package.zip",
        "sample-exports/job/manifest.json",
        MemoryWriter(),
    )
    completed = worker.build_completed_event(
        published,
        message_id="10000000-0000-4000-8000-000000000005",
        job_id="50000000-0000-4000-8000-000000000001",
        occurred_at="2026-08-03T00:04:00Z",
        idempotency_key="idem-sample-completed-1",
        traceparent="00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
    )
    assert b'"package"' in completed
    assert b'"manifest"' in completed

    bad_snapshot = dict(second.source_snapshot)
    bad_snapshot["image"] = dict(bad_snapshot["image"], sha256="0" * 64)
    partial = worker.build_package(
        [first, worker.CandidateInput(second.candidate_id, bad_snapshot)], reader, 1024 * 1024
    )
    assert partial.status == "FAILED"
    assert partial.exported_count == 1 and partial.failed_count == 1
    assert partial.failed_candidate_ids == (second.candidate_id,)

    missing_version = dict(first.source_snapshot)
    missing_result = worker.canonical_json(
        {"algorithm_outcome": "UNQUALIFIED", "confidence": 0.9, "defect_regions": []}
    )
    missing_version["result_reference"] = ref("c.json", missing_result, "application/json")
    missing = worker.build_package(
        [worker.CandidateInput(first.candidate_id, missing_version)],
        MemoryReader({"a.png": image, "c.json": missing_result}),
        1024 * 1024,
    )
    assert missing.status == "FAILED"
    assert missing.items[0].error_code == "VERSION_UNAVAILABLE"
    print("R7 sample export positive/negative/partial/hash/version cases: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
