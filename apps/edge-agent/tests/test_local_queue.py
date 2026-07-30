import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


EDGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDGE_ROOT / "src"))

from edge_agent.local_queue.database import EdgeQueue, QueueIntegrityError
from edge_agent.local_queue.models import LocalCaptureState, LocalImageRecord


class MutableClock:
    def __init__(self, value=1_000.0):
        self.value = float(value)

    def __call__(self):
        return self.value


def image_record(capture_id="capture-1", role="PRIMARY"):
    return LocalImageRecord(
        capture_id=capture_id,
        image_role=role,
        relative_path=Path("pending") / capture_id / f"{role.lower()}.png",
        sha256=hashlib.sha256(role.encode()).hexdigest(),
        size_bytes=len(role),
        width=16,
        height=16,
        media_type="image/png",
        upload_status="PENDING",
        central_image_id=None,
    )


class EdgeQueueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clock = MutableClock()
        self.queue = EdgeQueue(self.root / "edge_queue.sqlite3", clock=self.clock)

    def tearDown(self):
        self.queue.close()
        self.temporary.cleanup()

    def create_capture(self, capture_id="capture-1"):
        created = self.queue.create_capture(
            capture_id=capture_id,
            station_id="station-1",
            recipe_id="recipe-1",
            client_sequence=1,
            trigger_id=f"trigger-{capture_id}",
            trigger_source="PLC",
            occurred_at="2026-07-29T01:00:00Z",
            quality_status="OK",
            quality_warnings=(),
            manifest_path=Path("pending") / capture_id / "manifest.json",
            images=[image_record(capture_id)],
        )
        self.assertTrue(created)
        return self.queue.get_capture(capture_id)

    def test_database_enables_wal_foreign_keys_busy_wait_and_integrity(self):
        self.assertEqual("wal", self.queue.journal_mode)
        self.assertTrue(self.queue.foreign_keys_enabled)
        self.assertEqual(5_000, self.queue.busy_timeout_ms)
        self.queue.integrity_check()
        self.assertEqual(1, self.queue.get_agent_state("schema_version"))

    def test_constructor_rejects_database_that_cannot_enable_wal(self):
        real_connection = sqlite3.connect(":memory:", isolation_level=None)

        class NoWalConnection:
            def execute(self, sql, *args):
                if sql == "PRAGMA journal_mode = WAL":
                    return real_connection.execute("PRAGMA journal_mode")
                return real_connection.execute(sql, *args)

            def close(self):
                real_connection.close()

            def __getattr__(self, name):
                return getattr(real_connection, name)

        with patch(
            "edge_agent.local_queue.database.sqlite3.connect",
            return_value=NoWalConnection(),
        ):
            with self.assertRaisesRegex(QueueIntegrityError, "WAL"):
                EdgeQueue(self.root / "no-wal.sqlite3")

    def test_capture_creation_is_idempotent_but_rejects_changed_metadata(self):
        self.create_capture()
        duplicate = self.queue.create_capture(
            capture_id="capture-1",
            station_id="station-1",
            recipe_id="recipe-1",
            client_sequence=1,
            trigger_id="trigger-capture-1",
            trigger_source="PLC",
            occurred_at="2026-07-29T01:00:00Z",
            quality_status="OK",
            quality_warnings=(),
            manifest_path=Path("pending/capture-1/manifest.json"),
            images=[image_record()],
        )
        self.assertFalse(duplicate)
        with self.assertRaisesRegex(QueueIntegrityError, "不一致"):
            self.queue.create_capture(
                capture_id="capture-1",
                station_id="station-1",
                recipe_id="recipe-1",
                client_sequence=2,
                trigger_id="trigger-capture-1",
                trigger_source="PLC",
                occurred_at="2026-07-29T01:00:00Z",
                quality_status="OK",
                quality_warnings=(),
                manifest_path=Path("pending/capture-1/manifest.json"),
                images=[image_record()],
            )
        changed_image = image_record()
        changed_image = LocalImageRecord(
            **{
                **changed_image.__dict__,
                "sha256": "0" * 64,
            }
        )
        with self.assertRaisesRegex(QueueIntegrityError, "不一致"):
            self.queue.create_capture(
                capture_id="capture-1",
                station_id="station-1",
                recipe_id="recipe-1",
                client_sequence=1,
                trigger_id="trigger-capture-1",
                trigger_source="PLC",
                occurred_at="2026-07-29T01:00:00Z",
                quality_status="OK",
                quality_warnings=(),
                manifest_path=Path("pending/capture-1/manifest.json"),
                images=[changed_image],
            )

    def test_foreign_key_rejects_orphan_images(self):
        orphan = image_record("missing")
        with self.assertRaises(Exception):
            self.queue.update_image_upload(
                capture_id=orphan.capture_id,
                image_role=orphan.image_role,
                status="AVAILABLE",
            )

    def test_state_machine_rejects_regression_and_done_without_center_final_status(self):
        self.create_capture()
        self.queue.transition("capture-1", LocalCaptureState.UPLOADING)
        with self.assertRaisesRegex(QueueIntegrityError, "非法"):
            self.queue.transition("capture-1", LocalCaptureState.PENDING)
        self.queue.transition("capture-1", LocalCaptureState.UPLOADED)
        self.queue.transition("capture-1", LocalCaptureState.SUBMITTED)
        self.queue.transition("capture-1", LocalCaptureState.WAIT_RESULT)
        with self.assertRaisesRegex(QueueIntegrityError, "中心最终状态"):
            self.queue.transition("capture-1", LocalCaptureState.DONE)
        result = self.queue.transition(
            "capture-1",
            LocalCaptureState.DONE,
            central_status="FINALIZED",
        )
        self.assertEqual(LocalCaptureState.DONE, result.state)
        columns = {
            str(row[1])
            for row in self.queue._connection.execute(
                "PRAGMA table_info(capture_queue)"
            ).fetchall()
        }
        self.assertNotIn("business_disposition", columns)

    def test_retry_preserves_capture_id_and_resumes_previous_projection(self):
        self.create_capture()
        self.queue.transition("capture-1", LocalCaptureState.UPLOADING)
        retry = self.queue.schedule_retry(
            "capture-1",
            retry_at=1_010.0,
            error_code="TD-EDGE-TRANSIENT-001",
        )
        self.assertEqual("capture-1", retry.capture_id)
        self.assertEqual(LocalCaptureState.UPLOADING, retry.resume_state)
        self.assertEqual([], self.queue.due_captures(now=1_009.0))
        self.assertEqual(
            ["capture-1"],
            [item.capture_id for item in self.queue.due_captures(now=1_010.0)],
        )
        resumed = self.queue.transition("capture-1", LocalCaptureState.UPLOADING)
        self.assertEqual(LocalCaptureState.UPLOADING, resumed.state)

    def test_cleanup_candidates_only_include_final_center_confirmed_records(self):
        self.create_capture("done")
        for state in (
            LocalCaptureState.UPLOADING,
            LocalCaptureState.UPLOADED,
            LocalCaptureState.SUBMITTED,
            LocalCaptureState.WAIT_RESULT,
        ):
            self.queue.transition("done", state)
        self.queue.transition(
            "done",
            LocalCaptureState.DONE,
            central_status="FINALIZED",
        )
        self.create_capture("pending")
        self.clock.value += 100
        candidates = self.queue.find_cleanup_candidates(
            confirmed_before=self.clock.value
        )
        self.assertEqual(["done"], [item.capture_id for item in candidates])

    def test_queue_depth_and_oldest_age_ignore_terminal_records(self):
        self.create_capture()
        self.clock.value += 30
        self.assertEqual(1, self.queue.queue_depth())
        self.assertEqual(30, self.queue.oldest_unfinished_age_seconds())

    def test_wait_result_poll_schedule_suppresses_early_requests(self):
        self.create_capture()
        for state in (
            LocalCaptureState.UPLOADING,
            LocalCaptureState.UPLOADED,
            LocalCaptureState.SUBMITTED,
            LocalCaptureState.WAIT_RESULT,
        ):
            self.queue.transition("capture-1", state)
        self.queue.defer_poll("capture-1", next_poll_at=1_030.0)
        self.assertEqual([], self.queue.due_captures(now=1_029.9))
        self.assertEqual(
            ["capture-1"],
            [
                item.capture_id
                for item in self.queue.due_captures(now=1_030.0)
            ],
        )


if __name__ == "__main__":
    unittest.main()
