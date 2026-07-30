from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch


EDGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDGE_ROOT / "src"))

from edge_agent.capture.models import CapturedFrame
from edge_agent.capture.storage import (
    AtomicCaptureStore,
    CaptureStorageError,
    InjectedCrash,
)
from edge_agent.local_queue.database import EdgeQueue
from edge_agent.local_queue.models import LocalCaptureState
from device_fixtures import PNG


class CaptureStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.queue = EdgeQueue(self.root / "edge_queue.sqlite3")

    def tearDown(self):
        self.queue.close()
        self.temporary.cleanup()

    @staticmethod
    def frame(role="PRIMARY", content=None, metadata=None):
        return CapturedFrame(
            image_role=role,
            content=PNG if content is None else content,
            media_type="image/png",
            width=32,
            height=24,
            metadata={} if metadata is None else metadata,
        )

    def persist(self, store, capture_id="capture-1", frames=None):
        return store.persist(
            capture_id=capture_id,
            station_id="station-1",
            recipe_id="recipe-1",
            client_sequence=7,
            occurred_at="2026-07-29T01:00:00Z",
            frames=frames or [self.frame()],
            trigger_id="plc-7",
            trigger_source="PLC",
        )

    def test_atomic_persist_writes_manifest_hash_and_queue(self):
        store = AtomicCaptureStore(self.root, self.queue)
        result = self.persist(store)
        self.assertTrue((self.root / result.manifest_path).is_file())
        self.assertTrue(
            (self.root / result.images[0].relative_path).is_file()
        )
        self.assertEqual(64, len(result.images[0].sha256))
        self.assertEqual(
            LocalCaptureState.PENDING,
            self.queue.get_capture("capture-1").state,
        )

    def test_multiframe_roles_must_be_unique(self):
        store = AtomicCaptureStore(self.root, self.queue)
        with self.assertRaisesRegex(CaptureStorageError, "唯一"):
            self.persist(
                store,
                frames=[self.frame(), self.frame(content=b"other")],
            )

    def test_image_role_rejects_path_traversal_case_collisions_and_overflow(self):
        store = AtomicCaptureStore(self.root, self.queue)
        for role in ("../escaped", "a/b", r"a\b", "." * 65):
            with self.subTest(role=role):
                with self.assertRaisesRegex(CaptureStorageError, "image_role"):
                    self.persist(
                        store,
                        capture_id=f"capture-{len(role)}-{ord(role[0])}",
                        frames=[self.frame(role=role)],
                    )
        with self.assertRaisesRegex(CaptureStorageError, "唯一"):
            self.persist(
                store,
                capture_id="capture-case-collision",
                frames=[self.frame("PRIMARY"), self.frame("primary")],
            )
        with self.assertRaisesRegex(CaptureStorageError, "上限 16"):
            self.persist(
                store,
                capture_id="capture-too-many",
                frames=[self.frame(f"VIEW_{index}") for index in range(17)],
            )

    def test_all_black_image_is_retained_with_quality_warning(self):
        store = AtomicCaptureStore(self.root, self.queue)
        result = self.persist(
            store,
            frames=[self.frame(metadata={"all_black": True})],
        )
        self.assertEqual("WARNING", result.quality.status)
        self.assertIn("ALL_BLACK", result.quality.warnings)
        self.assertTrue((self.root / result.images[0].relative_path).exists())

    def test_complete_staging_directory_is_recovered_on_startup(self):
        def crash(stage):
            if stage == "after_file_sync":
                raise InjectedCrash(stage)

        store = AtomicCaptureStore(self.root, self.queue, crash_hook=crash)
        with self.assertRaises(InjectedCrash):
            self.persist(store)
        recovered = AtomicCaptureStore(self.root, self.queue).recover()
        self.assertEqual(["capture-1"], recovered["recovered"])
        self.assertEqual([], recovered["quarantined"])
        self.assertIsNotNone(self.queue.get_capture("capture-1"))

    def test_directory_fsync_failure_is_explicit_and_preserves_quarantine(self):
        store = AtomicCaptureStore(self.root, self.queue)
        with patch(
            "edge_agent.capture.storage.os.open",
            side_effect=OSError("目录同步失败"),
        ):
            with self.assertRaisesRegex(OSError, "目录同步失败"):
                self.persist(store)
        self.assertIsNone(self.queue.get_capture("capture-1"))
        quarantined = list((self.root / "quarantine").iterdir())
        self.assertEqual(1, len(quarantined))
        self.assertTrue((quarantined[0] / "primary.png").is_file())

    def test_incomplete_staging_directory_is_quarantined_on_startup(self):
        incomplete = self.root / "staging" / "broken.tmp"
        incomplete.mkdir(parents=True)
        (incomplete / "primary.png").write_bytes(PNG)
        recovered = AtomicCaptureStore(self.root, self.queue).recover()
        self.assertEqual([], recovered["recovered"])
        self.assertEqual(["broken.tmp"], recovered["quarantined"])
        quarantined = next((self.root / "quarantine").iterdir())
        self.assertEqual(PNG, (quarantined / "primary.png").read_bytes())

    def test_crash_after_rename_recovers_queue_from_manifest(self):
        def crash(stage):
            if stage == "after_directory_rename":
                raise InjectedCrash(stage)

        store = AtomicCaptureStore(self.root, self.queue, crash_hook=crash)
        with self.assertRaises(InjectedCrash):
            self.persist(store)
        self.assertIsNone(self.queue.get_capture("capture-1"))
        result = AtomicCaptureStore(self.root, self.queue).recover()
        self.assertEqual(["capture-1"], result["recovered"])
        self.assertEqual(
            LocalCaptureState.PENDING,
            self.queue.get_capture("capture-1").state,
        )

    def test_crash_after_sqlite_commit_is_idempotent_on_restart(self):
        def crash(stage):
            if stage == "after_sqlite_commit":
                raise InjectedCrash(stage)

        store = AtomicCaptureStore(self.root, self.queue, crash_hook=crash)
        with self.assertRaises(InjectedCrash):
            self.persist(store)
        self.assertIsNotNone(self.queue.get_capture("capture-1"))
        result = AtomicCaptureStore(self.root, self.queue).recover()
        self.assertEqual({"recovered": [], "quarantined": []}, result)
        self.assertEqual(1, len(self.queue.list_images("capture-1")))

    def test_sqlite_write_failure_is_rebuilt_from_pending_manifest(self):
        store = AtomicCaptureStore(self.root, self.queue)
        with patch.object(
            self.queue,
            "create_capture",
            side_effect=sqlite3.OperationalError("database is busy"),
        ):
            with self.assertRaisesRegex(sqlite3.OperationalError, "busy"):
                self.persist(store)
        self.assertIsNone(self.queue.get_capture("capture-1"))
        self.assertTrue((self.root / "pending" / "capture-1").is_dir())
        result = store.recover()
        self.assertEqual(["capture-1"], result["recovered"])
        self.assertIsNotNone(self.queue.get_capture("capture-1"))

    def test_corrupt_pending_file_moves_to_quarantine_without_deletion(self):
        store = AtomicCaptureStore(self.root, self.queue)
        result = self.persist(store)
        # 模拟 SQLite 丢失后又发现磁盘文件；先新建空库。
        self.queue.close()
        (self.root / "edge_queue.sqlite3").unlink()
        for suffix in ("-wal", "-shm"):
            sidecar = self.root / f"edge_queue.sqlite3{suffix}"
            if sidecar.exists():
                sidecar.unlink()
        self.queue = EdgeQueue(self.root / "edge_queue.sqlite3")
        image_path = self.root / result.images[0].relative_path
        image_path.write_bytes(b"tampered")
        recovered = AtomicCaptureStore(self.root, self.queue).recover()
        self.assertEqual([], recovered["recovered"])
        self.assertEqual(["capture-1"], recovered["quarantined"])
        quarantine_items = list((self.root / "quarantine").iterdir())
        self.assertEqual(1, len(quarantine_items))
        self.assertTrue((quarantine_items[0] / "primary.png").is_file())

    def test_recovery_rechecks_hash_when_queue_record_already_exists(self):
        store = AtomicCaptureStore(self.root, self.queue)
        result = self.persist(store)
        image_path = self.root / result.images[0].relative_path
        image_path.write_bytes(b"tampered-after-sqlite-commit")
        recovered = store.recover()
        self.assertEqual([], recovered["recovered"])
        self.assertEqual(["capture-1"], recovered["quarantined"])
        self.assertEqual(
            LocalCaptureState.LOCAL_DEAD,
            self.queue.get_capture("capture-1").state,
        )
        self.assertFalse(self.queue.cleanup_enabled)
        quarantined = next((self.root / "quarantine").iterdir())
        self.assertEqual(
            b"tampered-after-sqlite-commit",
            (quarantined / "primary.png").read_bytes(),
        )

    def test_nonempty_undecodable_image_is_retained_and_marked_rejected(self):
        store = AtomicCaptureStore(self.root, self.queue)
        result = self.persist(
            store,
            frames=[self.frame(content=b"not-an-image")],
        )
        self.assertEqual("REJECTED", result.quality.status)
        self.assertIn("IMAGE_DECODE_FAILED", result.quality.warnings)
        image_path = self.root / result.images[0].relative_path
        self.assertEqual(b"not-an-image", image_path.read_bytes())

    def test_only_done_capture_can_move_and_cleanup(self):
        store = AtomicCaptureStore(self.root, self.queue)
        self.persist(store)
        with self.assertRaisesRegex(CaptureStorageError, "中心最终确认"):
            store.mark_confirmed("capture-1")
        for state in (
            LocalCaptureState.UPLOADING,
            LocalCaptureState.UPLOADED,
            LocalCaptureState.SUBMITTED,
            LocalCaptureState.WAIT_RESULT,
        ):
            self.queue.transition("capture-1", state)
        done = self.queue.transition(
            "capture-1",
            LocalCaptureState.DONE,
            central_status="FINALIZED",
        )
        confirmed = store.mark_confirmed("capture-1")
        self.assertTrue(confirmed.is_dir())
        audit = store.cleanup_confirmed(
            confirmed_before=done.confirmed_at,
        )
        self.assertEqual("capture-1", audit[0]["capture_id"])
        self.assertFalse(confirmed.exists())
        persisted_audit = self.queue.get_cleanup_audit("capture-1")
        self.assertIsNotNone(persisted_audit)
        self.assertIsNotNone(persisted_audit["completed_at"])
        self.assertEqual(
            tuple(audit[0]["sha256"]),
            persisted_audit["sha256"],
        )

    def test_cleanup_revalidates_confirmed_bytes_before_deletion(self):
        store = AtomicCaptureStore(self.root, self.queue)
        self.persist(store)
        for state in (
            LocalCaptureState.UPLOADING,
            LocalCaptureState.UPLOADED,
            LocalCaptureState.SUBMITTED,
            LocalCaptureState.WAIT_RESULT,
        ):
            self.queue.transition("capture-1", state)
        done = self.queue.transition(
            "capture-1",
            LocalCaptureState.DONE,
            central_status="FINALIZED",
        )
        confirmed = store.mark_confirmed("capture-1")
        (confirmed / "primary.png").write_bytes(b"tampered-after-confirmation")
        with self.assertRaisesRegex(CaptureStorageError, "完整性复核失败"):
            store.cleanup_confirmed(confirmed_before=done.confirmed_at)
        self.assertFalse(confirmed.exists())
        quarantined = next((self.root / "quarantine").iterdir())
        self.assertEqual(
            b"tampered-after-confirmation",
            (quarantined / "primary.png").read_bytes(),
        )
        self.assertIsNone(self.queue.get_cleanup_audit("capture-1"))
        self.assertFalse(self.queue.cleanup_enabled)

    def test_disk_thresholds_pause_before_unsafe_deletion(self):
        store = AtomicCaptureStore(self.root, self.queue)
        thresholds = dict(
            warning_ratio=0.8,
            high_ratio=0.9,
            critical_ratio=0.95,
        )
        self.assertEqual("NORMAL", store.disk_action(usage_ratio=0.79, **thresholds))
        self.assertEqual("WARN", store.disk_action(usage_ratio=0.8, **thresholds))
        self.assertEqual(
            "ACCELERATE_CONFIRMED_CLEANUP",
            store.disk_action(usage_ratio=0.91, **thresholds),
        )
        self.assertEqual(
            "PAUSE_CAPTURE",
            store.disk_action(usage_ratio=0.96, **thresholds),
        )


if __name__ == "__main__":
    unittest.main()
