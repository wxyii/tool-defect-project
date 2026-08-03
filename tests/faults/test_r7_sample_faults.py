from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class R7SampleFaultTest(unittest.TestCase):
    def test_worker_hash_and_version_faults_are_explicit_and_never_pass(self) -> None:
        worker = (ROOT / "jobs/sample-export-worker/worker.py").read_text(encoding="utf-8")
        self.assertIn('"OBJECT_HASH_CONFLICT"', worker)
        self.assertIn('"VERSION_UNAVAILABLE"', worker)
        self.assertIn('status = "SUCCEEDED" if not failed_ids else "FAILED"', worker)
        self.assertNotIn('status = "PASS"', worker)

    def test_partial_export_has_manifest_failure_counts_and_failure_ids(self) -> None:
        worker = (ROOT / "jobs/sample-export-worker/worker.py").read_text(encoding="utf-8")
        for marker in (
            '"failed_count"',
            '"failed_candidate_ids"',
            '"error_detail_digest"',
            '"format_version": "r7-sample-export/1"',
        ):
            self.assertIn(marker, worker)
        migration = (
            ROOT
            / "services/business-api/src/main/resources/db/migration/V20__r7_sample_library_and_exports.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("status IN ('QUEUED', 'EXPORTED', 'FAILED')", migration)
        self.assertIn("ck_sample_export_manifest", migration)

    def test_storage_failure_is_retryable_not_a_success(self) -> None:
        worker = (ROOT / "jobs/sample-export-worker/worker.py").read_text(encoding="utf-8")
        self.assertIn("class RetryableExportFailure", worker)
        self.assertIn("raise RetryableExportFailure", worker)
        self.assertNotIn("except RetryableExportFailure:\n        return PublishedExport", worker)


if __name__ == "__main__":
    unittest.main()
