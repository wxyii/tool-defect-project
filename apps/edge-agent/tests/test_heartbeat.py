from pathlib import Path
import sys
import tempfile
import unittest


EDGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDGE_ROOT / "src"))

from edge_agent.capture.models import CapturedFrame
from edge_agent.capture.storage import AtomicCaptureStore
from edge_agent.adapters import CameraScenario, SimulatedCameraAdapter
from edge_agent.health.heartbeat import HeartbeatBuilder
from edge_agent.local_queue.database import EdgeQueue
from edge_agent.telemetry import MetricRegistry
from device_fixtures import PNG


class HeartbeatTests(unittest.TestCase):
    def test_unknown_clock_offset_fails_and_simulator_uses_contract_health(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = EdgeQueue(root / "edge_queue.sqlite3")
            try:
                camera = SimulatedCameraAdapter([CameraScenario.no_image()])
                builder = HeartbeatBuilder(
                    queue=queue,
                    data_root=root,
                    agent_version="edge-agent/0.1.0",
                    camera_health=camera.health,
                    trigger_health=lambda: {"status": "ONLINE"},
                )
                with self.assertRaisesRegex(ValueError, "未测量"):
                    builder.build(time_offset_ms=None)
                self.assertEqual("ONLINE", camera.health()["status"])
            finally:
                queue.close()

    def test_heartbeat_reports_projection_and_device_health_without_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = EdgeQueue(root / "edge_queue.sqlite3", clock=lambda: 100.0)
            try:
                metrics = MetricRegistry({"station", "device_type"})
                AtomicCaptureStore(root, queue).persist(
                    capture_id="capture-1",
                    station_id="station-1",
                    recipe_id="recipe-1",
                    client_sequence=1,
                    occurred_at="2026-07-29T01:00:00Z",
                    frames=[
                        CapturedFrame(
                            "PRIMARY",
                            PNG,
                            width=32,
                            height=24,
                        )
                    ],
                    trigger_id="plc-1",
                    trigger_source="PLC",
                )
                payload = HeartbeatBuilder(
                    queue=queue,
                    data_root=root,
                    agent_version="edge-agent/0.1.0",
                    camera_health=lambda: {"status": "ONLINE"},
                    trigger_health=lambda: {"status": "DEGRADED"},
                    metrics=metrics,
                    station_id="station-1",
                    clock=lambda: 130.0,
                ).build(time_offset_ms=3.5)
                self.assertEqual(
                    {
                        "agent_version",
                        "reported_at",
                        "queue_depth",
                        "oldest_task_age_seconds",
                        "disk_usage_ratio",
                        "camera_status",
                        "plc_status",
                        "clock_offset_ms",
                    },
                    set(payload),
                )
                self.assertEqual(1, payload["queue_depth"])
                self.assertEqual(30.0, payload["oldest_task_age_seconds"])
                self.assertEqual("ONLINE", payload["camera_status"])
                self.assertEqual("DEGRADED", payload["plc_status"])
                self.assertEqual(
                    "1970-01-01T00:02:10.000Z",
                    payload["reported_at"],
                )
                serialized = repr(payload).lower()
                self.assertNotIn("token", serialized)
                self.assertNotIn("password", serialized)
                self.assertNotIn("business_disposition", serialized)
                rendered = metrics.render_prometheus()
                self.assertIn(
                    'tool_defect_edge_queue_depth{station="station-1"} 1',
                    rendered,
                )
                self.assertIn(
                    (
                        "tool_defect_edge_device_online"
                        '{device_type="camera",station="station-1"} 1'
                    ),
                    rendered,
                )
                self.assertIn(
                    (
                        "tool_defect_edge_device_online"
                        '{device_type="plc",station="station-1"} 0'
                    ),
                    rendered,
                )
            finally:
                queue.close()


if __name__ == "__main__":
    unittest.main()
