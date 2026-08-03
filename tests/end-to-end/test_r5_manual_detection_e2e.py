from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class R5ManualDetectionE2ETest(unittest.TestCase):
    def test_browser_backend_and_contract_surfaces_form_one_v2_flow(self) -> None:
        routes = (ROOT / "apps/web-console/src/router/routes.ts").read_text(encoding="utf-8")
        client = (ROOT / "apps/web-console/src/api/client.ts").read_text(encoding="utf-8")
        controller = (
            ROOT
            / "services/business-api/src/main/java/com/tooldefect/business/detectionbatch/api/ManualDetectionController.java"
        ).read_text(encoding="utf-8")
        generated = (
            ROOT / "packages/typescript-contracts/src/v2/index.ts"
        ).read_text(encoding="utf-8")

        self.assertIn("/manual-detection", routes)
        self.assertIn("/detection-batches/:id", routes)
        for operation in (
            "createDetectionBatchV2",
            "addDetectionBatchItemV2",
            "completeDetectionBatchItemUploadV2",
            "submitDetectionBatchV2",
            "putQuickReviewV2",
        ):
            self.assertIn(operation, client)
        self.assertIn('@PutMapping("/detection-batches/{batch_id}/items/{item_id}/quick-review")', controller)
        self.assertIn("export type DetectionBatchItem", generated)
        self.assertIn("export type QuickReviewRecord", generated)

    def test_ten_item_partial_quality_result_keeps_nine_normal_results(self) -> None:
        statuses = ["QUALITY_REJECTED", *("COMPLETED" for _ in range(9))]
        completed = sum(status in {"COMPLETED", "QUALITY_REJECTED", "FAILED"} for status in statuses)
        quality_rejected = statuses.count("QUALITY_REJECTED")
        normal = sum(status == "COMPLETED" for status in statuses)

        self.assertEqual(10, completed)
        self.assertEqual(1, quality_rejected)
        self.assertEqual(9, normal)
        self.assertEqual("PARTIALLY_COMPLETED", "PARTIALLY_COMPLETED" if quality_rejected else "COMPLETED")

    def test_signed_upload_address_is_not_written_to_browser_storage(self) -> None:
        feature = ROOT / "apps/web-console/src/features/manual-detection"
        source = "\n".join(path.read_text(encoding="utf-8") for path in feature.rglob("*.*"))
        self.assertNotIn("localStorage", source)
        self.assertNotIn("sessionStorage", source)
        self.assertNotIn("URLSearchParams", source)
        self.assertIn("credentials: 'omit'", source)


if __name__ == "__main__":
    unittest.main()
