from pathlib import Path
import sys
import tempfile
import unittest


EDGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDGE_ROOT / "src"))

from edge_agent.capture.models import CapturedFrame
from edge_agent.capture.coordinator import CaptureCoordinator, TriggerGuard
from edge_agent.capture.storage import AtomicCaptureStore, CaptureStorageError
from edge_agent.adapters import SimulatedCameraAdapter, TriggerEvent
from edge_agent.local_queue.database import EdgeQueue
from edge_agent.local_queue.models import LocalCaptureState
from edge_agent.local_queue.recovery import open_queue_with_recovery
from device_fixtures import PNG


class QueueRecoveryTests(unittest.TestCase):
    def test_corrupt_database_is_backed_up_and_rebuilt_from_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "edge_queue.sqlite3"
            queue = EdgeQueue(database, clock=lambda: 1_000.0)
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
            queue.close()
            database.write_bytes(b"not-a-sqlite-database")

            result = open_queue_with_recovery(
                database,
                data_root=root,
                clock=lambda: 2_000.0,
            )
            try:
                self.assertTrue(result.center_reconciliation_required)
                self.assertEqual(
                    ("capture-1",),
                    result.recovered_capture_ids,
                )
                self.assertEqual(1, len(result.backup_paths))
                self.assertEqual(
                    b"not-a-sqlite-database",
                    result.backup_paths[0].read_bytes(),
                )
                self.assertEqual(
                    LocalCaptureState.PENDING,
                    result.queue.get_capture("capture-1").state,
                )
                camera = SimulatedCameraAdapter([])
                duplicate = CaptureCoordinator(
                    camera=camera,
                    store=AtomicCaptureStore(root, result.queue),
                    trigger_guard=TriggerGuard(0.2),
                    station_id="station-1",
                    recipe_id="recipe-1",
                    capture_id_factory=lambda: "must-not-be-created",
                ).handle(
                    TriggerEvent(
                        trigger_id="plc-1",
                        sequence=1,
                        occurred_at="2026-07-29T01:00:00Z",
                        occurred_monotonic=5.0,
                        source="PLC",
                    )
                )
                self.assertEqual("DUPLICATE", duplicate.status)
                self.assertEqual([], camera.calls)
                self.assertFalse(result.queue.cleanup_enabled)
                with self.assertRaisesRegex(
                    CaptureStorageError,
                    "禁止清理",
                ):
                    AtomicCaptureStore(root, result.queue).cleanup_confirmed(
                        confirmed_before=2_000.0
                    )
            finally:
                result.queue.close()


if __name__ == "__main__":
    unittest.main()
