from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
for source in (
    ROOT / "apps/edge-agent/src",
    ROOT / "packages/python-contracts/src",
    ROOT / "services/inference-service/src",
):
    sys.path.insert(0, str(source))

from edge_agent.sync.generated_client import _request
from edge_agent.telemetry import TraceContext as EdgeTraceContext
from inference_service.telemetry import TraceContext as InferenceTraceContext


CAPTURE_ID = "019f0000-0000-7000-8000-000000000701"
REQUEST_ID = "request-p5-cross-component-1"


class P5TraceIntegrationTest(unittest.TestCase):
    def test_production_trace_crosses_edge_backend_queue_and_inference(self):
        request = _request(
            path={"capture_id": CAPTURE_ID},
            headers={"X-Request-Id": REQUEST_ID},
            body={"requested_at": "2026-07-30T08:00:00.000Z"},
        )
        traceparent = request["headers"]["traceparent"]
        edge = EdgeTraceContext.parse(traceparent)
        inference = InferenceTraceContext.parse(traceparent)
        self.assertEqual(edge.trace_id, inference.trace_id)
        self.assertEqual(
            hashlib.sha256(CAPTURE_ID.encode("utf-8")).hexdigest()[:32],
            edge.trace_id,
        )

        production_source = (
            ROOT
            / "services/business-api/src/main/java/com/tooldefect/business"
            / "detectionbatch/application/ProductionDetectionService.java"
        ).read_text(encoding="utf-8")
        publisher_source = (
            ROOT
            / "services/business-api/src/main/java/com/tooldefect/business"
            / "shared/infrastructure/RabbitMessagePublisher.java"
        ).read_text(encoding="utf-8")
        self.assertIn('payload.put("traceparent", traceparent)', production_source)
        self.assertIn('"tool_defect.inference.item.requested.v2"', production_source)
        self.assertIn('"pipeline_version", "2.0.0"', production_source)
        self.assertIn(
            'builder.setHeader("traceparent", identity.traceparent())',
            publisher_source,
        )

    def test_logs_do_not_expose_query_secrets_bodies_or_stack_paths(self):
        filter_source = (
            ROOT
            / "services/business-api/src/main/java/com/tooldefect/business"
            / "shared/infrastructure/TelemetryRequestFilter.java"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "getQueryString()",
            "getReader()",
            "getInputStream()",
            'getHeader("Authorization")',
            'getHeader("Cookie")',
            "getStackTrace()",
        ):
            self.assertNotIn(forbidden, filter_source)
        self.assertIn("request.getRequestURI()", filter_source)


if __name__ == "__main__":
    unittest.main()
