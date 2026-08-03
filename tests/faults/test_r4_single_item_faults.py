from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
for source in (
    ROOT / "packages/python-contracts/src",
    ROOT / "apps/edge-agent/src",
):
    sys.path.insert(0, str(source))

from edge_agent.sync.production_v2 import ProductionImage, ProductionItemClientAdapter
from tool_defect_contracts.v2 import CONTRACT_SOURCE_SHA256


class _Client:
    contract_source_sha256 = CONTRACT_SOURCE_SHA256

    def createProductionDetectionItemV2(self, request=None):
        return {
            "capture_id": request["body"]["capture_id"],
            "batch_id": "20000000-0000-4000-8000-000000000001",
            "batch_item_id": "30000000-0000-4000-8000-000000000001",
            "detection_task_id": "40000000-0000-4000-8000-000000000001",
            "status": "QUEUED",
        }


class R4SingleItemFaultTest(unittest.TestCase):
    def test_duplicate_capture_with_changed_hash_fails_explicitly(self):
        adapter = ProductionItemClientAdapter(
            _Client(), expected_contract_sha256=CONTRACT_SOURCE_SHA256
        )
        arguments = {
            "capture_id": "10000000-0000-4000-8000-000000000001",
            "idempotency_key": "r4-fault-item-1",
            "request_id": "r4-fault-request-1",
        }
        adapter.submit(image=_image("a"), **arguments)

        with self.assertRaisesRegex(ValueError, "哈希冲突"):
            adapter.submit(image=_image("b"), **arguments)

    def test_technical_failure_and_quality_rejection_cannot_be_pass(self):
        handler = (
            ROOT / "services/business-api/src/main/java/com/tooldefect/business/detectionbatch/infrastructure/R4InferenceResultHandler.java"
        ).read_text(encoding="utf-8")
        migration = (
            ROOT / "services/business-api/src/main/resources/db/migration/V18__r4_single_item_inference.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("'FAILED',?,?)", handler)
        self.assertIn('rejected?"QUALITY_REJECTED":"COMPLETED"', handler)
        self.assertNotIn("status='PASS'", handler)
        self.assertIn("technical_failed + summary.quality_rejected", migration)


def _image(digest):
    return ProductionImage(
        bucket="td-original",
        object_key="production-originals/station/capture.png",
        sha256=digest * 64,
        size_bytes=1024,
        media_type="image/png",
    )


if __name__ == "__main__":
    unittest.main()
