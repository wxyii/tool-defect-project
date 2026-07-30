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
from edge_agent.local_queue.database import EdgeQueue
from edge_agent.telemetry import MetricRegistry
from device_fixtures import png_bytes


def frame(role="PRIMARY", *, suffix=b"", metadata=None):
    value = 127 if not suffix else 20 + sum(suffix) % 216
    return CapturedFrame(
        role,
        png_bytes(value=value),
        width=32,
        height=24,
        metadata={} if metadata is None else metadata,
    )


def trigger(trigger_id, sequence, monotonic):
    return TriggerEvent(
        trigger_id=trigger_id,
        sequence=sequence,
        occurred_at="2026-07-29T01:00:00Z",
        occurred_monotonic=monotonic,
        source="PLC",
    )


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.queue = EdgeQueue(self.root / "edge_queue.sqlite3")
        self.store = AtomicCaptureStore(self.root, self.queue)
        self.metrics = MetricRegistry({"station", "result"})

    def tearDown(self):
        self.queue.close()
        self.temporary.cleanup()

    def coordinator(self, camera, ids=None, retries=1):
        values = iter(ids or ["capture-1", "capture-2", "capture-3"])
        return CaptureCoordinator(
            camera=camera,
            store=self.store,
            trigger_guard=TriggerGuard(0.2),
            station_id="station-1",
            recipe_id="recipe-1",
            capture_id_factory=lambda: next(values),
            camera_busy_retries=retries,
            metrics=self.metrics,
        )

    def test_duplicate_trigger_is_debounced_without_second_camera_call(self):
        camera = SimulatedCameraAdapter(
            [CameraScenario.success(frame())]
        )
        coordinator = self.coordinator(camera)
        first = coordinator.handle(trigger("same", 1, 1.0))
        second = coordinator.handle(trigger("same", 1, 1.1))
        self.assertEqual("OK", first.status)
        self.assertEqual("DUPLICATE", second.status)
        self.assertEqual(["same"], camera.calls)
        self.assertIn(
            (
                "tool_defect_edge_captures_total"
                '{result="ok",station="station-1"} 1'
            ),
            self.metrics.render_prometheus(),
        )

    def test_duplicate_trigger_remains_debounced_after_process_restart(self):
        first_camera = SimulatedCameraAdapter(
            [CameraScenario.success(frame())]
        )
        self.coordinator(first_camera).handle(trigger("same", 1, 1.0))

        restarted_camera = SimulatedCameraAdapter(
            [CameraScenario.success(frame())]
        )
        restarted = self.coordinator(
            restarted_camera,
            ids=["capture-after-restart"],
        ).handle(trigger("same", 1, 1.1))
        self.assertEqual("DUPLICATE", restarted.status)
        self.assertEqual([], restarted_camera.calls)
        incident = self.queue.get_trigger(source="PLC", trigger_id="same")
        self.assertEqual("OK", incident["outcome_status"])
        self.assertEqual("capture-1", incident["capture_id"])

    def test_crash_after_trigger_claim_resumes_same_capture_id(self):
        event = trigger("crashed", 9, 9.0)
        self.queue.claim_trigger(
            source=event.source,
            trigger_id=event.trigger_id,
            sequence=event.sequence,
            occurred_at=event.occurred_at,
            occurred_monotonic=event.occurred_monotonic,
            capture_id="capture-before-crash",
            outcome_status="CAPTURE_STARTED",
        )
        camera = SimulatedCameraAdapter(
            [CameraScenario.success(frame())]
        )
        result = self.coordinator(
            camera,
            ids=["must-not-be-used"],
        ).handle(event)
        self.assertEqual("capture-before-crash", result.capture_id)
        self.assertEqual("QUALITY_WARNING", result.status)
        self.assertIn("RESUMED_AFTER_CRASH", result.warnings)
        self.assertEqual(["crashed"], camera.calls)
        self.assertIsNotNone(
            self.queue.get_capture("capture-before-crash")
        )

    def test_startup_recovery_marks_unreplayable_claim_for_manual_hold(self):
        event = trigger("not-replayed", 11, 11.0)
        self.queue.claim_trigger(
            source=event.source,
            trigger_id=event.trigger_id,
            sequence=event.sequence,
            occurred_at=event.occurred_at,
            occurred_monotonic=event.occurred_monotonic,
            capture_id="capture-not-replayed",
            outcome_status="CAPTURE_STARTED",
        )
        camera = SimulatedCameraAdapter(
            [CameraScenario.success(frame())]
        )
        outcomes = self.coordinator(camera).recover_incomplete_triggers()
        self.assertEqual(1, len(outcomes))
        self.assertEqual("QUALITY_REJECTED", outcomes[0].status)
        self.assertIn(
            "CAPTURE_INTERRUPTED_REQUIRES_HOLD",
            outcomes[0].warnings,
        )
        self.assertEqual([], camera.calls)
        incident = self.queue.get_trigger(
            source=event.source,
            trigger_id=event.trigger_id,
        )
        self.assertEqual("QUALITY_REJECTED", incident["outcome_status"])
        self.assertEqual(
            "TD-CAMERA-INTERRUPTED-001",
            incident["error_code"],
        )

    def test_crash_after_sqlite_commit_repairs_trigger_outcome(self):
        event = trigger("committed", 10, 10.0)
        self.queue.claim_trigger(
            source=event.source,
            trigger_id=event.trigger_id,
            sequence=event.sequence,
            occurred_at=event.occurred_at,
            occurred_monotonic=event.occurred_monotonic,
            capture_id="capture-committed",
            outcome_status="CAPTURE_STARTED",
        )
        self.store.persist(
            capture_id="capture-committed",
            station_id="station-1",
            recipe_id="recipe-1",
            client_sequence=event.sequence,
            occurred_at=event.occurred_at,
            frames=[frame()],
            trigger_id=event.trigger_id,
            trigger_source=event.source,
        )
        camera = SimulatedCameraAdapter(
            [CameraScenario.success(frame())]
        )
        result = self.coordinator(camera).handle(event)
        self.assertEqual("DUPLICATE", result.status)
        self.assertEqual([], camera.calls)
        incident = self.queue.get_trigger(
            source=event.source,
            trigger_id=event.trigger_id,
        )
        self.assertEqual("OK", incident["outcome_status"])

    def test_sequence_gap_is_preserved_as_quality_warning(self):
        camera = SimulatedCameraAdapter(
            [
                CameraScenario.success(frame(suffix=b"one")),
                CameraScenario.success(frame(suffix=b"two")),
            ]
        )
        coordinator = self.coordinator(camera)
        coordinator.handle(trigger("one", 1, 1.0))
        result = coordinator.handle(trigger("two", 4, 2.0))
        self.assertEqual("QUALITY_WARNING", result.status)
        self.assertIn("TRIGGER_SEQUENCE_GAP", result.warnings)
        incident = self.queue.get_trigger(source="PLC", trigger_id="two")
        self.assertEqual("one", incident["related_trigger_id"])
        self.assertTrue((self.root / result.persisted.images[0].relative_path).exists())

    def test_camera_busy_retries_within_window(self):
        camera = SimulatedCameraAdapter(
            [
                CameraScenario.busy(),
                CameraScenario.success(frame()),
            ]
        )
        result = self.coordinator(camera, retries=1).handle(trigger("one", 1, 1.0))
        self.assertEqual("OK", result.status)
        self.assertEqual(["one", "one"], camera.calls)

    def test_camera_busy_exhaustion_and_no_image_are_explicit_failures(self):
        busy = self.coordinator(
            SimulatedCameraAdapter([CameraScenario.busy()]),
            retries=0,
        ).handle(trigger("busy", 1, 1.0))
        self.assertEqual("QUALITY_REJECTED", busy.status)
        self.assertEqual("TD-CAMERA-TRANSIENT-001", busy.error_code)

        no_image = self.coordinator(
            SimulatedCameraAdapter([CameraScenario.no_image()]),
            ids=["capture-no-image"],
        ).handle(trigger("empty", 2, 2.0))
        self.assertEqual("QUALITY_REJECTED", no_image.status)
        self.assertIn("NO_IMAGE", no_image.warnings)
        incident = self.queue.get_trigger(source="PLC", trigger_id="empty")
        self.assertEqual("QUALITY_REJECTED", incident["outcome_status"])
        self.assertIn("NO_IMAGE", incident["warnings"])
        self.assertEqual("TD-CAMERA-VALIDATION-001", incident["error_code"])

    def test_corrupt_and_all_black_images_are_not_silently_dropped(self):
        corrupt = self.coordinator(
            SimulatedCameraAdapter([CameraScenario.corrupt()]),
        ).handle(trigger("corrupt", 1, 1.0))
        self.assertEqual("QUALITY_REJECTED", corrupt.status)
        self.assertIsNotNone(corrupt.persisted)
        corrupt_path = self.root / corrupt.persisted.images[0].relative_path
        self.assertEqual(b"not-an-image", corrupt_path.read_bytes())

        black = self.coordinator(
            SimulatedCameraAdapter(
                [
                    CameraScenario.success(frame(metadata={"all_black": True}))
                ]
            ),
            ids=["capture-black"],
        ).handle(trigger("black", 2, 2.0))
        self.assertEqual("QUALITY_WARNING", black.status)
        self.assertTrue((self.root / black.persisted.images[0].relative_path).exists())

    def test_multiview_frames_keep_distinct_roles(self):
        camera = SimulatedCameraAdapter(
            [
                CameraScenario.success(
                    frame("PRIMARY", suffix=b"primary"),
                    frame("SIDE", suffix=b"side"),
                )
            ]
        )
        result = self.coordinator(camera).handle(trigger("multi", 1, 1.0))
        self.assertEqual(
            {"PRIMARY", "SIDE"},
            {image.image_role for image in result.persisted.images},
        )


if __name__ == "__main__":
    unittest.main()
