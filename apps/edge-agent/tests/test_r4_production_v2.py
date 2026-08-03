import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/python-contracts/src"))
sys.path.insert(0, str(ROOT / "tools/verify-contracts"))
sys.path.insert(0, str(ROOT / "apps/edge-agent/src"))

from edge_agent.sync.production_v2 import ProductionImage, ProductionItemClientAdapter
from edge_agent.telemetry import MetricRegistry
from schema_engine import SchemaEngine
from tool_defect_contracts.v2 import CONTRACT_SOURCE_SHA256
from verify_contracts import resolve_openapi


CAPTURE_ID = "10000000-0000-4000-8000-000000000001"


class _GeneratedV2:
    contract_source_sha256 = CONTRACT_SOURCE_SHA256

    def __init__(self):
        self.requests = []

    def createProductionDetectionItemV2(self, request=None):
        self.requests.append(request)
        return {
            "capture_id": request["body"]["capture_id"],
            "batch_id": "20000000-0000-4000-8000-000000000001",
            "batch_item_id": "30000000-0000-4000-8000-000000000001",
            "detection_task_id": "40000000-0000-4000-8000-000000000001",
            "status": "QUEUED",
        }


class ProductionV2AdapterTests(unittest.TestCase):
    def setUp(self):
        self.generated = _GeneratedV2()
        self.metrics = MetricRegistry({"contract_version", "result"})
        self.adapter = ProductionItemClientAdapter(
            self.generated,
            expected_contract_sha256=CONTRACT_SOURCE_SHA256,
            metrics=self.metrics,
        )

    def test_single_object_request_uses_generated_v2_operation_and_schema(self):
        accepted = self.adapter.submit(
            capture_id=CAPTURE_ID,
            image=_image(),
            idempotency_key="production-item-0001",
            request_id="request-r4-1",
        )

        self.assertEqual(accepted.status, "QUEUED")
        request = self.generated.requests[0]
        self.assertEqual(set(request["body"]), {"capture_id", "image"})
        self.assertNotIn("images", request["body"])
        api_path = ROOT / "contracts/openapi/tool-defect-api-v2.json"
        api = json.loads(api_path.read_text(encoding="utf-8"))
        schema = resolve_openapi(api["components"]["schemas"]["ProductionItemRequest"], api)
        SchemaEngine().validate(request["body"], schema, api_path, "")

    def test_duplicate_trigger_reuses_capture_and_hash_conflict_is_rejected(self):
        arguments = dict(
            capture_id=CAPTURE_ID,
            image=_image(),
            idempotency_key="production-item-0001",
            request_id="request-r4-1",
        )
        first = self.adapter.submit(**arguments)
        second = self.adapter.submit(**arguments)
        self.assertEqual(first, second)

        conflicting = ProductionImage(
            bucket="td-original",
            object_key="production-originals/station/capture.png",
            sha256="b" * 64,
            size_bytes=1024,
            media_type="image/png",
        )
        with self.assertRaisesRegex(ValueError, "哈希冲突"):
            self.adapter.submit(**{**arguments, "image": conflicting})

    def test_v1_and_v2_usage_metrics_remain_distinguishable(self):
        self.adapter.submit(
            capture_id=CAPTURE_ID,
            image=_image(),
            idempotency_key="production-item-0001",
            request_id="request-r4-1",
        )
        snapshot = self.metrics.snapshot()
        self.assertIn(
            (
                "tool_defect_edge_contract_requests_total",
                (("contract_version", "v2"), ("result", "accepted")),
            ),
            snapshot,
        )


def _image():
    return ProductionImage(
        bucket="td-original",
        object_key="production-originals/station/capture.png",
        sha256="a" * 64,
        size_bytes=1024,
        media_type="image/png",
        object_version="version-1",
    )
