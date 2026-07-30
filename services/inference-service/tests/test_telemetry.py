import io
import json
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVICE_SRC = PROJECT_ROOT / "services/inference-service/src"
sys.path.insert(0, str(SERVICE_SRC))

from inference_service.telemetry import (
    JsonTelemetry,
    MetricRegistry,
    TraceContext,
)


TRACEPARENT = (
    "00-0123456789abcdef0123456789abcdef-0123456789abcdef-00"
)


class TelemetryTests(unittest.TestCase):
    def test_errors_are_emitted_even_when_trace_is_not_sampled(self):
        stream = io.StringIO()
        telemetry = JsonTelemetry(
            service="inference-service",
            service_version="commit-1",
            environment="test",
            host="worker-1",
            stream=stream,
            clock=lambda: 1_722_300_000.0,
        )
        event = telemetry.emit(
            "inference.failed",
            "推理失败",
            level="ERROR",
            traceparent=TRACEPARENT,
            capture_id="019f0000-0000-7000-8000-000000000001",
            error_code="TD-MODEL-INCOMPATIBLE-001",
            retryable=False,
            token="must-not-leak",
            object_url="https://storage.invalid/a?signature=must-not-leak",
        )

        self.assertFalse(event["trace_sampled"])
        self.assertEqual(event["token"], "[REDACTED]")
        self.assertEqual(
            event["object_url"],
            "https://storage.invalid/a",
        )
        body = stream.getvalue()
        self.assertEqual(json.loads(body), event)
        self.assertNotIn("must-not-leak", body)

    def test_metrics_use_bounded_dimensions(self):
        metrics = MetricRegistry(
            {"pipeline_version", "model_version", "result", "stage"}
        )
        metrics.increment(
            "tool_defect_inference_requests_total",
            labels={
                "pipeline_version": "pipeline-1",
                "model_version": "model-1",
                "result": "success",
                "stage": "complete",
            },
        )
        self.assertIn(
            "tool_defect_inference_requests_total",
            metrics.render_prometheus(),
        )
        with self.assertRaises(ValueError):
            metrics.set_gauge(
                "tool_defect_inference_ready",
                1,
                labels={"attempt_id": "high-cardinality"},
            )

    def test_histogram_exports_cumulative_buckets_sum_and_count(self):
        metrics = MetricRegistry({"model_version", "stage"})
        labels = {"model_version": "model-1", "stage": "inference"}
        metrics.observe_histogram(
            "tool_defect_inference_stage_duration_seconds",
            0.2,
            buckets=(0.1, 0.25, 1.0),
            labels=labels,
        )
        rendered = metrics.render_prometheus()
        self.assertNotIn('le="0.1"} 1', rendered)
        self.assertIn('le="0.25",model_version="model-1"', rendered)
        self.assertIn('le="+Inf",model_version="model-1"', rendered)
        self.assertIn(
            "tool_defect_inference_stage_duration_seconds_sum"
            '{model_version="model-1",stage="inference"} 0.2',
            rendered,
        )
        self.assertIn(
            "tool_defect_inference_stage_duration_seconds_count"
            '{model_version="model-1",stage="inference"} 1',
            rendered,
        )
        with self.assertRaises(ValueError):
            metrics.observe_histogram(
                "tool_defect_inference_stage_duration_seconds",
                0.2,
                buckets=(1.0, 0.1),
                labels=labels,
            )

    def test_invalid_event_and_trace_are_rejected(self):
        stream = io.StringIO()
        telemetry = JsonTelemetry(
            service="inference-service",
            service_version="1",
            environment="test",
            stream=stream,
        )
        with self.assertRaises(ValueError):
            telemetry.emit("unstable", "bad")
        with self.assertRaises(ValueError):
            TraceContext.parse("invalid")


if __name__ == "__main__":
    unittest.main()
