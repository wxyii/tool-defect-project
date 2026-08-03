from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class R3ManualDetectionFaultTest(unittest.TestCase):
    def test_object_integrity_failure_records_hold_before_error(self) -> None:
        service = (ROOT / "services/business-api/src/main/java/com/tooldefect/business/detectionbatch/application/ManualDetectionBatchService.java").read_text(encoding="utf-8")
        failure = service.index('recordUploadFailure(batchId, itemId, actor, "TD-STORAGE-INTEGRITY-001")')
        rejection = service.index('throw violation(Kind.INTEGRITY, "对象头、大小、媒体类型或 SHA-256 冲突")')
        self.assertLess(failure, rejection)

    def test_compensation_facts_are_append_only_and_never_pass(self) -> None:
        migration = (ROOT / "services/business-api/src/main/resources/db/migration/V17__r3_manual_detection_batches.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE r3_compensation_event", migration)
        self.assertIn("status IN ('PENDING', 'RESOLVED', 'HOLD')", migration)
        self.assertNotIn("'PASS'", migration)
        self.assertIn("trg_r3_compensation_event_append_only", migration)

    def test_expired_uploads_enter_orphan_cleanup_queue(self) -> None:
        repository = (ROOT / "services/business-api/src/main/java/com/tooldefect/business/detectionbatch/infrastructure/JdbcManualDetectionRepository.java").read_text(encoding="utf-8")
        configuration = (ROOT / "services/business-api/src/main/java/com/tooldefect/business/detectionbatch/infrastructure/ManualDetectionConfiguration.java").read_text(encoding="utf-8")
        self.assertIn("state='ORPHANED'", repository)
        self.assertIn("recordOrphanCleanup(orphan,false", repository)
        self.assertIn("@Scheduled", configuration)


if __name__ == "__main__":
    unittest.main()
