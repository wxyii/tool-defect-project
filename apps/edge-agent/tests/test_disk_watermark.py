from pathlib import Path
import sys
import tempfile
import unittest


EDGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDGE_ROOT / "src"))

from edge_agent.adapters import (
    CameraScenario,
    SimulatedCameraAdapter,
    TriggerEvent,
)
from edge_agent.capture.coordinator import CaptureCoordinator, TriggerGuard
from edge_agent.capture.models import CapturedFrame
from edge_agent.capture.storage import AtomicCaptureStore
from edge_agent.health.disk_watermark import DiskWatermarkController
from edge_agent.local_queue.database import EdgeQueue
from device_fixtures import png_bytes


class DiskWatermarkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.queue = EdgeQueue(self.root / "edge.sqlite3")
        self.store = AtomicCaptureStore(self.root, self.queue)

    def tearDown(self):
        self.queue.close()
        self.temporary.cleanup()

    def test_exact_watermarks_warn_cleanup_and_pause(self):
        cleanups = []

        warning = self.controller(0.80, cleanups).before_capture()
        high = self.controller(0.90, cleanups).before_capture()
        critical = self.controller(0.95, cleanups).before_capture()

        self.assertEqual("WARNING", warning.level)
        self.assertTrue(warning.allow_capture)
        self.assertEqual("HIGH", high.level)
        self.assertTrue(high.accelerated_cleanup)
        self.assertEqual(1, high.cleaned_capture_count)
        self.assertEqual("CRITICAL", critical.level)
        self.assertFalse(critical.allow_capture)
        self.assertEqual(["cleanup"], cleanups)

    def test_unknown_usage_pauses_instead_of_assuming_capacity(self):
        decision = self.controller(float("nan"), []).before_capture()

        self.assertEqual("UNKNOWN", decision.level)
        self.assertFalse(decision.allow_capture)

    def test_critical_watermark_does_not_claim_trigger_or_call_camera(self):
        camera = SimulatedCameraAdapter(
            [
                CameraScenario.success(
                    CapturedFrame(
                        "PRIMARY",
                        png_bytes(value=127),
                        width=32,
                        height=24,
                    )
                )
            ]
        )
        coordinator = CaptureCoordinator(
            camera=camera,
            store=self.store,
            trigger_guard=TriggerGuard(0.2),
            station_id="station-1",
            recipe_id="recipe-1",
            capture_id_factory=lambda: "capture-1",
            disk_watermark=self.controller(0.95, []),
        )
        event = TriggerEvent(
            trigger_id="trigger-paused",
            sequence=1,
            occurred_at="2026-07-30T00:00:00Z",
            occurred_monotonic=1.0,
            source="PLC",
        )

        outcome = coordinator.handle(event)

        self.assertEqual("PAUSED", outcome.status)
        self.assertEqual(("DISK_CRITICAL",), outcome.warnings)
        self.assertEqual([], camera.calls)
        self.assertIsNone(
            self.queue.get_trigger(source="PLC", trigger_id="trigger-paused")
        )

    @staticmethod
    def controller(ratio, cleanups):
        def cleanup():
            cleanups.append("cleanup")
            return 1

        return DiskWatermarkController(
            usage_ratio=lambda: ratio,
            cleanup_confirmed=cleanup,
        )


if __name__ == "__main__":
    unittest.main()
