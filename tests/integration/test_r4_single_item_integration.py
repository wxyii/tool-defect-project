from pathlib import Path
import json
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
for source in (
    ROOT / "src",
    ROOT / "services/inference-service/src",
):
    sys.path.insert(0, str(source))

from inference_service.orchestration.single_item import SingleItemTask


class R4SingleItemIntegrationTest(unittest.TestCase):
    def test_manual_and_production_requests_share_the_same_single_item_shape(self):
        manual = _payload("manual-originals", "manual-originals/batch/item.png")
        production = _payload(
            "td-original", "production-originals/station/capture.png"
        )

        for payload in (manual, production):
            task = SingleItemTask.from_contract(payload)
            self.assertIsNone(task.image.image_role)
            self.assertEqual(task.pipeline_version, "2.0.0")

    def test_frozen_v2_contract_and_business_route_have_one_image(self):
        contract = json.loads(
            (ROOT / "contracts/json-schema/event-payloads-v2.schema.json")
            .read_text(encoding="utf-8")
        )
        request = contract["$defs"]["InferenceItemRequested"]
        self.assertIn("image", request["required"])
        self.assertNotIn("images", request["properties"])
        self.assertNotIn("image_role", json.dumps(request))

        topology = (
            ROOT / "services/business-api/src/main/java/com/tooldefect/business/shared/infrastructure/RabbitTopology.java"
        ).read_text(encoding="utf-8")
        self.assertIn('with("inference.item.requested.v2")', topology)


def _payload(bucket: str, object_key: str):
    return {
        "message_id": "10000000-0000-4000-8000-000000000001",
        "occurred_at": "2026-08-03T00:00:00Z",
        "idempotency_key": "r4-integration-item-1",
        "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
        "batch_item_id": "20000000-0000-4000-8000-000000000001",
        "detection_task_id": "30000000-0000-4000-8000-000000000001",
        "image": {
            "bucket": bucket,
            "object_key": object_key,
            "sha256": "a" * 64,
            "size_bytes": 1024,
            "media_type": "image/png",
        },
        "pipeline_version": "2.0.0",
    }


if __name__ == "__main__":
    unittest.main()
