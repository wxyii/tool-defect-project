import io
import json
from pathlib import Path
import sys
import unittest


EDGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDGE_ROOT / "src"))

from edge_agent.telemetry import JsonTelemetry, MetricRegistry, TraceContext


TRACEPARENT = (
    "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
)


class TelemetryTests(unittest.TestCase):
    def test_json_event_is_correlated_and_redacted(self):
        stream = io.StringIO()
        telemetry = JsonTelemetry(
            service="edge-agent",
            service_version="commit-1",
            environment="test",
            host="edge-1",
            stream=stream,
            clock=lambda: 1_722_300_000.0,
        )

        event = telemetry.emit(
            "capture.persisted",
            "采集原图已安全落盘",
            traceparent=TRACEPARENT,
            capture_id="019f0000-0000-7000-8000-000000000001",
            signed_url="https://storage.invalid/object?signature=secret",
            local_path="/private/data/raw.png",
            authorization="Bearer secret",
            image_bytes=b"not-for-logs",
        )

        encoded = stream.getvalue()
        self.assertEqual(json.loads(encoded), event)
        self.assertEqual(
            event["trace_id"],
            "0123456789abcdef0123456789abcdef",
        )
        self.assertEqual(event["signed_url"], "[REDACTED]")
        self.assertEqual(event["authorization"], "[REDACTED]")
        self.assertEqual(event["local_path"], "[LOCAL_PATH_REDACTED]")
        self.assertEqual(event["image_bytes"], "[REDACTED]")
        self.assertNotIn("Bearer secret", encoded)
        self.assertNotIn("signature=secret", encoded)
        self.assertNotIn("not-for-logs", encoded)

    def test_metrics_reject_high_cardinality_labels(self):
        with self.assertRaises(ValueError):
            MetricRegistry({"capture_id"})
        metrics = MetricRegistry({"station", "result"})
        metrics.increment(
            "tool_defect_edge_captures_total",
            labels={"station": "station-a", "result": "success"},
        )
        rendered = metrics.render_prometheus()
        self.assertIn("tool_defect_edge_captures_total", rendered)
        self.assertNotIn("capture_id", rendered)
        with self.assertRaises(ValueError):
            metrics.increment(
                "tool_defect_edge_captures_total",
                labels={"capture_id": "high-cardinality"},
            )

    def test_traceparent_rejects_zero_identity(self):
        with self.assertRaises(ValueError):
            TraceContext.parse(
                "00-" + "0" * 32 + "-" + "1" * 16 + "-01"
            )


if __name__ == "__main__":
    unittest.main()
