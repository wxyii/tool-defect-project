import random
from pathlib import Path
import sys
import tempfile
import unittest


EDGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDGE_ROOT / "src"))

from edge_agent.capture.models import CapturedFrame
from edge_agent.capture.storage import AtomicCaptureStore
from edge_agent.local_queue.database import EdgeQueue
from edge_agent.local_queue.models import LocalCaptureState
from edge_agent.sync.backoff import BackoffPolicy
from edge_agent.sync.client import (
    CaptureInitialization,
    CentralCapture,
    DetectionSubmission,
    SyncClientError,
    SyncService,
    UploadTicket,
)
from device_fixtures import PNG


class Clock:
    def __init__(self, value=1_000.0):
        self.value = float(value)

    def __call__(self):
        return self.value


class FakeClient:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.uploads = []
        self.central = {}
        self.failure = None
        self.ticket_expiry = clock() + 300
        self.renewals = 0

    def maybe_fail(self, operation):
        if self.failure and self.failure[0] == operation:
            error = self.failure[1]
            self.failure = None
            raise error

    def initialize_capture(
        self, *, capture, images, idempotency_key, request_id
    ):
        self.maybe_fail("initialize")
        self.calls.append(("initialize", capture.capture_id, idempotency_key))
        return CaptureInitialization(
            capture_id=capture.capture_id,
            central_status="UPLOADING",
            upload_tickets=tuple(
                UploadTicket(
                    image_id=f"image-{image.image_role.lower()}",
                    image_role=image.image_role,
                    url="https://upload.invalid/one",
                    method="PUT",
                    headers={"Content-Type": image.media_type},
                    expires_at=self.ticket_expiry,
                )
                for image in images
            ),
        )

    def renew_upload_ticket(
        self, *, capture_id, image, idempotency_key, request_id
    ):
        self.renewals += 1
        self.calls.append(
            ("renew", capture_id, image.image_role, idempotency_key)
        )
        return UploadTicket(
            image_id=image.central_image_id or f"image-{image.image_role.lower()}",
            image_role=image.image_role,
            url="https://upload.invalid/renewed",
            method="PUT",
            headers={},
            expires_at=self.clock() + 300,
        )

    def upload_image(self, *, ticket, file_path, sha256, size_bytes):
        self.maybe_fail("upload")
        self.calls.append(("upload", ticket.image_id, sha256))
        self.uploads.append(file_path.read_bytes())
        return "etag-opaque"

    def complete_image(
        self,
        *,
        capture_id,
        image_id,
        sha256,
        size_bytes,
        upload_receipt,
        idempotency_key,
        request_id,
    ):
        self.maybe_fail("complete")
        self.calls.append(
            ("complete", capture_id, idempotency_key, upload_receipt)
        )

    def submit_detection(
        self, *, capture_id, idempotency_key, request_id
    ):
        self.maybe_fail("submit")
        self.calls.append(("submit", capture_id, idempotency_key))
        return DetectionSubmission(
            capture_id=capture_id,
            detection_task_id=f"detection-{capture_id}",
            pipeline_version="production-r8/1",
            poll_after_ms=500,
        )

    def get_capture(self, *, capture_id, request_id):
        self.maybe_fail("get")
        self.calls.append(("get", capture_id, request_id))
        return self.central.get(
            capture_id,
            CentralCapture(capture_id, "PROCESSING", None, 500),
        )

    def reconcile_captures(self, *, capture_ids, request_id):
        self.maybe_fail("reconcile")
        self.calls.append(("reconcile", tuple(capture_ids), request_id))
        return [
            self.central[capture_id]
            for capture_id in capture_ids
            if capture_id in self.central
        ]

    def send_heartbeat(self, **kwargs):
        self.maybe_fail("heartbeat")
        self.calls.append(
            (
                "heartbeat",
                kwargs["device_id"],
                kwargs["idempotency_key"],
                kwargs["request_id"],
                kwargs["payload"],
            )
        )


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clock = Clock()
        self.queue = EdgeQueue(
            self.root / "edge_queue.sqlite3",
            clock=self.clock,
        )
        self.store = AtomicCaptureStore(self.root, self.queue)
        self.store.persist(
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
        self.client = FakeClient(self.clock)
        self.request_counter = 0

        def request_id():
            self.request_counter += 1
            return f"request-{self.request_counter}"

        self.final_results = []
        self.service = SyncService(
            queue=self.queue,
            client=self.client,
            data_root=self.root,
            backoff=BackoffPolicy(jitter_ratio=0),
            clock=self.clock,
            request_id_factory=request_id,
            final_result_handler=self.final_results.append,
            confirmed_handler=self.store.mark_confirmed,
        )

    def tearDown(self):
        self.queue.close()
        self.temporary.cleanup()

    def run_until_wait_result(self, *, make_due=True):
        for _ in range(4):
            self.service.run_once()
        record = self.queue.get_capture("capture-1")
        self.assertEqual(
            LocalCaptureState.WAIT_RESULT,
            record.state,
        )
        if make_due:
            self.clock.value = record.next_poll_at

    def test_final_and_confirmation_handlers_are_required(self):
        with self.assertRaises(TypeError):
            SyncService(
                queue=self.queue,
                client=self.client,
                data_root=self.root,
                backoff=BackoffPolicy(jitter_ratio=0),
            )

    def test_full_online_sync_preserves_capture_id_and_idempotency_keys(self):
        self.run_until_wait_result()
        self.client.central["capture-1"] = CentralCapture(
            "capture-1",
            "FINALIZED",
            "PASS",
        )
        self.service.run_once()
        record = self.queue.get_capture("capture-1")
        self.assertEqual(LocalCaptureState.DONE, record.state)
        self.assertFalse(hasattr(record, "business_disposition"))
        self.assertEqual("PASS", self.final_results[0].business_disposition)
        self.assertIn(
            ("initialize", "capture-1", "station-1:capture-1:create"),
            self.client.calls,
        )
        self.assertIn(
            ("submit", "capture-1", "capture-1:submit"),
            self.client.calls,
        )
        self.assertEqual([PNG], self.client.uploads)
        self.assertTrue((self.root / "confirmed" / "capture-1").is_dir())

    def test_expired_upload_ticket_is_renewed(self):
        self.client.ticket_expiry = self.clock() - 1
        self.service.run_once()
        self.service.run_once()
        self.assertEqual(1, self.client.renewals)
        self.assertEqual(
            LocalCaptureState.UPLOADED,
            self.queue.get_capture("capture-1").state,
        )

    def test_server_rejected_ticket_is_invalidated_and_renewed(self):
        self.service.run_once()
        self.client.failure = (
            "upload",
            SyncClientError(
                "签名票据已过期",
                code="TD-UPLOAD-FORBIDDEN",
                status_code=403,
                retryable=True,
            ),
        )
        result = self.service.run_once()
        self.assertEqual(["capture-1"], result["retried"])
        retry = self.queue.get_capture("capture-1")
        self.clock.value = retry.retry_at
        self.service.run_once()
        self.assertEqual(1, self.client.renewals)
        self.assertEqual(1, len(self.client.uploads))
        self.assertEqual(
            LocalCaptureState.UPLOADED,
            self.queue.get_capture("capture-1").state,
        )

    def test_upload_receipt_survives_confirmation_timeout_without_reupload(self):
        self.service.run_once()
        self.client.failure = ("complete", TimeoutError("确认超时"))
        result = self.service.run_once()
        self.assertEqual(["capture-1"], result["retried"])
        image = self.queue.list_images("capture-1")[0]
        self.assertEqual("UPLOADED", image.upload_status)
        self.assertEqual("etag-opaque", image.upload_receipt)
        self.assertEqual(1, len(self.client.uploads))

        retry = self.queue.get_capture("capture-1")
        self.clock.value = retry.retry_at
        self.service.run_once()
        self.assertEqual(1, len(self.client.uploads))
        self.assertEqual(
            "AVAILABLE",
            self.queue.list_images("capture-1")[0].upload_status,
        )

    def test_expired_receipt_during_complete_forces_renewal_and_reupload(self):
        self.service.run_once()
        self.client.failure = (
            "complete",
            SyncClientError(
                "上传会话已过期",
                code="TD-STORAGE-EXPIRED-001",
                status_code=409,
                retryable=False,
            ),
        )
        result = self.service.run_once()
        self.assertEqual(["capture-1"], result["retried"])
        image = self.queue.list_images("capture-1")[0]
        self.assertEqual("PENDING", image.upload_status)
        self.assertIsNone(image.upload_receipt)

        retry = self.queue.get_capture("capture-1")
        self.clock.value = retry.retry_at
        self.service.run_once()
        self.assertEqual(1, self.client.renewals)
        self.assertEqual(2, len(self.client.uploads))
        self.assertEqual(
            "AVAILABLE",
            self.queue.list_images("capture-1")[0].upload_status,
        )

    def test_storage_integrity_failure_reuploads_once_then_stops(self):
        failure = lambda: SyncClientError(
            "中心对象哈希不一致",
            code="TD-STORAGE-INTEGRITY-001",
            status_code=422,
            retryable=False,
        )
        self.service.run_once()
        self.client.failure = ("complete", failure())
        first = self.service.run_once()
        self.assertEqual(["capture-1"], first["retried"])
        self.assertEqual(
            1,
            self.queue.get_agent_state(
                "integrity_reupload:capture-1:PRIMARY"
            ),
        )

        retry = self.queue.get_capture("capture-1")
        self.clock.value = retry.retry_at
        self.client.failure = ("complete", failure())
        second = self.service.run_once()
        self.assertEqual(["capture-1"], second["failed"])
        self.assertEqual(2, len(self.client.uploads))
        self.assertEqual(
            LocalCaptureState.LOCAL_DEAD,
            self.queue.get_capture("capture-1").state,
        )
        self.assertTrue(
            (self.root / "pending" / "capture-1" / "primary.png").is_file()
        )

    def test_503_retries_same_capture_with_documented_backoff(self):
        self.client.failure = (
            "initialize",
            SyncClientError(
                "暂不可用",
                code="TD-API-TRANSIENT-001",
                status_code=503,
                retryable=True,
            ),
        )
        result = self.service.run_once()
        self.assertEqual(["capture-1"], result["retried"])
        record = self.queue.get_capture("capture-1")
        self.assertEqual(LocalCaptureState.RETRY_WAIT, record.state)
        self.assertEqual(LocalCaptureState.PENDING, record.resume_state)
        self.assertEqual(self.clock() + 1, record.retry_at)
        self.clock.value = record.retry_at
        self.service.run_once()
        self.assertEqual(
            LocalCaptureState.UPLOADING,
            self.queue.get_capture("capture-1").state,
        )

    def test_global_auth_failure_pauses_without_killing_queued_captures(self):
        self.store.persist(
            capture_id="capture-2",
            station_id="station-1",
            recipe_id="recipe-1",
            client_sequence=2,
            occurred_at="2026-07-29T01:00:01Z",
            frames=[CapturedFrame("PRIMARY", PNG, width=32, height=24)],
            trigger_id="plc-2",
            trigger_source="PLC",
        )
        self.client.failure = (
            "initialize",
            SyncClientError(
                "设备令牌失效",
                code="TD-AUTH-UNAUTHORIZED-001",
                status_code=401,
                retryable=False,
            ),
        )
        result = self.service.run_once()
        self.assertEqual(["capture-1"], result["paused"])
        self.assertTrue(self.service.auth_pause_active)
        self.assertEqual(
            LocalCaptureState.PENDING,
            self.queue.get_capture("capture-1").state,
        )
        self.assertEqual(
            LocalCaptureState.PENDING,
            self.queue.get_capture("capture-2").state,
        )

        calls_before = list(self.client.calls)
        self.assertEqual([], self.service.run_once()["paused"])
        self.assertEqual(calls_before, self.client.calls)
        with self.assertRaisesRegex(SyncClientError, "暂停"):
            self.service.reconcile()

        self.service.resume_after_auth_recovery()
        self.service.run_once()
        self.assertFalse(self.service.auth_pause_active)
        self.assertEqual(
            LocalCaptureState.UPLOADING,
            self.queue.get_capture("capture-1").state,
        )
        self.assertEqual(
            LocalCaptureState.UPLOADING,
            self.queue.get_capture("capture-2").state,
        )

    def test_heartbeat_auth_failure_also_persists_global_pause(self):
        self.client.failure = (
            "heartbeat",
            SyncClientError(
                "客户端证书失效",
                code="TD-AUTH-MTLS-001",
                retryable=False,
            ),
        )
        with self.assertRaises(SyncClientError):
            self.service.send_heartbeat(
                device_id="device-1",
                payload={"camera_status": "ONLINE"},
            )
        self.assertTrue(self.service.auth_pause_active)
        pause = self.queue.get_agent_state("sync_auth_pause")
        self.assertEqual("TD-AUTH-MTLS-001", pause["error_code"])
        with self.assertRaisesRegex(SyncClientError, "暂停"):
            self.service.send_heartbeat(
                device_id="device-1",
                payload={"camera_status": "ONLINE"},
            )

    def test_429_respects_retry_after_and_nonretryable_conflict_stops(self):
        self.client.failure = (
            "initialize",
            SyncClientError(
                "限流",
                code="TD-API-TRANSIENT-429",
                status_code=429,
                retryable=True,
                retry_after_seconds=42,
            ),
        )
        self.service.run_once()
        self.assertEqual(
            self.clock() + 42,
            self.queue.get_capture("capture-1").retry_at,
        )

        self.clock.value += 42
        self.client.failure = (
            "initialize",
            SyncClientError(
                "幂等冲突",
                code="TD-API-CONFLICT-001",
                status_code=409,
                retryable=False,
            ),
        )
        result = self.service.run_once()
        self.assertEqual(["capture-1"], result["failed"])
        self.assertEqual(
            LocalCaptureState.LOCAL_DEAD,
            self.queue.get_capture("capture-1").state,
        )
        self.assertTrue(
            (self.root / "pending" / "capture-1" / "primary.png").exists()
        )

    def test_reconciliation_only_advances_local_projection(self):
        self.client.central["capture-1"] = CentralCapture(
            "capture-1",
            "FINALIZED",
            "FAIL",
        )
        advanced = self.service.reconcile()
        self.assertEqual(["capture-1"], advanced)
        record = self.queue.get_capture("capture-1")
        self.assertEqual(LocalCaptureState.DONE, record.state)
        self.assertEqual("FAIL", self.final_results[0].business_disposition)

        # 中心随后返回落后状态也不能回退本地最终投影。
        self.client.central["capture-1"] = CentralCapture(
            "capture-1",
            "UPLOADING",
            None,
        )
        self.assertEqual([], self.service.reconcile())
        self.assertEqual(
            LocalCaptureState.DONE,
            self.queue.get_capture("capture-1").state,
        )

    def test_poll_response_cannot_advance_a_different_capture(self):
        self.run_until_wait_result()
        self.store.persist(
            capture_id="capture-2",
            station_id="station-1",
            recipe_id="recipe-1",
            client_sequence=2,
            occurred_at="2026-07-29T01:00:01Z",
            frames=[
                CapturedFrame(
                    "PRIMARY",
                    PNG,
                    width=32,
                    height=24,
                )
            ],
            trigger_id="plc-2",
            trigger_source="PLC",
        )
        self.client.central["capture-1"] = CentralCapture(
            "capture-2",
            "FINALIZED",
            "PASS",
        )

        result = self.service.run_once(limit=1)

        self.assertEqual(["capture-1"], result["failed"])
        self.assertEqual(
            LocalCaptureState.LOCAL_DEAD,
            self.queue.get_capture("capture-1").state,
        )
        self.assertEqual(
            LocalCaptureState.PENDING,
            self.queue.get_capture("capture-2").state,
        )
        self.assertEqual([], self.final_results)

    def test_duplicate_final_response_is_idempotent(self):
        response = CentralCapture(
            "capture-1",
            "FINALIZED",
            "FAIL",
        )

        self.assertTrue(self.service._advance_from_central(response))
        self.assertFalse(self.service._advance_from_central(response))

        self.assertEqual(
            LocalCaptureState.DONE,
            self.queue.get_capture("capture-1").state,
        )
        self.assertEqual(
            ["FAIL"],
            [item.business_disposition for item in self.final_results],
        )

    def test_rebuilt_pending_projection_replays_create_before_center_uploading(self):
        self.client.central["capture-1"] = CentralCapture(
            "capture-1",
            "UPLOADING",
            "HOLD",
        )
        self.assertEqual([], self.service.reconcile())
        self.assertEqual(
            LocalCaptureState.PENDING,
            self.queue.get_capture("capture-1").state,
        )
        self.assertIsNone(
            self.queue.list_images("capture-1")[0].central_image_id
        )
        self.service.run_once()
        self.assertEqual(
            LocalCaptureState.UPLOADING,
            self.queue.get_capture("capture-1").state,
        )
        self.assertIsNotNone(
            self.queue.list_images("capture-1")[0].central_image_id
        )

    def test_unknown_central_status_fails_safe_without_pass(self):
        self.client.central["capture-1"] = CentralCapture(
            "capture-1",
            "NEW_UNKNOWN_STATE",
            None,
        )
        with self.assertRaises(SyncClientError):
            self.service.reconcile()
        record = self.queue.get_capture("capture-1")
        self.assertEqual(LocalCaptureState.PENDING, record.state)
        self.assertEqual([], self.final_results)

    def test_final_response_without_disposition_fails_incompatible(self):
        self.client.central["capture-1"] = CentralCapture(
            "capture-1",
            "FINALIZED",
            None,
        )
        with self.assertRaisesRegex(SyncClientError, "业务处置"):
            self.service.reconcile()
        self.assertNotEqual(
            LocalCaptureState.DONE,
            self.queue.get_capture("capture-1").state,
        )
        self.assertEqual([], self.final_results)

    def test_failed_status_cannot_be_mapped_to_pass(self):
        self.client.central["capture-1"] = CentralCapture(
            "capture-1",
            "FAILED",
            "PASS",
        )
        with self.assertRaisesRegex(SyncClientError, "FAILED"):
            self.service.reconcile()
        self.assertNotEqual(
            LocalCaptureState.DONE,
            self.queue.get_capture("capture-1").state,
        )
        self.assertEqual([], self.final_results)

    def test_final_delivery_failure_does_not_commit_done(self):
        self.run_until_wait_result()
        self.client.central["capture-1"] = CentralCapture(
            "capture-1",
            "FINALIZED",
            "PASS",
        )

        def fail_delivery(_):
            raise RuntimeError("显示器暂不可用")

        self.service.final_result_handler = fail_delivery
        result = self.service.run_once()
        self.assertEqual(["capture-1"], result["retried"])
        record = self.queue.get_capture("capture-1")
        self.assertEqual(LocalCaptureState.RETRY_WAIT, record.state)
        self.assertEqual(LocalCaptureState.WAIT_RESULT, record.resume_state)

        self.service.final_result_handler = self.final_results.append
        self.clock.value = record.retry_at
        self.service.run_once()
        self.assertEqual(
            LocalCaptureState.DONE,
            self.queue.get_capture("capture-1").state,
        )
        self.assertEqual(["PASS"], [
            item.business_disposition for item in self.final_results
        ])

    def test_confirmation_callback_is_persisted_and_retried_after_done(self):
        self.run_until_wait_result()
        self.client.central["capture-1"] = CentralCapture(
            "capture-1",
            "FINALIZED",
            "HOLD",
        )
        self.service.confirmed_handler = lambda _: (_ for _ in ()).throw(
            OSError("目录确认暂时失败")
        )
        self.service.run_once()
        self.assertEqual(
            LocalCaptureState.DONE,
            self.queue.get_capture("capture-1").state,
        )
        self.assertEqual(
            ["capture-1"],
            self.queue.get_agent_state("pending_confirmations"),
        )
        self.assertTrue((self.root / "pending" / "capture-1").is_dir())

        self.service.confirmed_handler = self.store.mark_confirmed
        self.service.run_once()
        self.assertEqual(
            [],
            self.queue.get_agent_state("pending_confirmations"),
        )
        self.assertTrue((self.root / "confirmed" / "capture-1").is_dir())

    def test_poll_after_suppresses_tight_result_polling(self):
        self.run_until_wait_result(make_due=False)
        self.service.run_once()
        record = self.queue.get_capture("capture-1")
        self.assertEqual(self.clock() + 0.5, record.next_poll_at)
        get_calls = [call for call in self.client.calls if call[0] == "get"]
        self.service.run_once()
        self.assertEqual(
            get_calls,
            [call for call in self.client.calls if call[0] == "get"],
        )
        self.clock.value += 0.5
        self.service.run_once()
        self.assertEqual(
            len(get_calls) + 1,
            len([call for call in self.client.calls if call[0] == "get"]),
        )

    def test_poll_bounds_and_reconcile_batch_limit_fail_explicitly(self):
        self.client.central["capture-1"] = CentralCapture(
            "capture-1",
            "PROCESSING",
            "HOLD",
            900_001,
        )
        with self.assertRaisesRegex(SyncClientError, "poll_after_ms"):
            self.service.reconcile()
        for invalid_limit in (0, 201):
            with self.subTest(limit=invalid_limit):
                with self.assertRaisesRegex(ValueError, "1..200"):
                    self.service.reconcile(limit=invalid_limit)

    def test_full_first_reconcile_batch_does_not_enable_cleanup_when_more_exist(self):
        self.store.persist(
            capture_id="capture-2",
            station_id="station-1",
            recipe_id="recipe-1",
            client_sequence=2,
            occurred_at="2026-07-29T01:00:01Z",
            frames=[CapturedFrame("PRIMARY", PNG, width=32, height=24)],
            trigger_id="plc-2",
            trigger_source="PLC",
        )
        self.queue.set_cleanup_enabled(False)
        self.client.central["capture-1"] = CentralCapture(
            "capture-1",
            "PROCESSING",
            "HOLD",
            500,
        )
        self.service.reconcile(limit=1)
        self.assertFalse(self.queue.cleanup_enabled)

    def test_heartbeat_has_real_send_path_and_idempotency(self):
        payload = {
            "agent_version": "edge-agent/0.1.0",
            "reported_at": "2026-07-29T01:00:00.000Z",
            "queue_depth": 1,
            "oldest_task_age_seconds": 0.0,
            "disk_usage_ratio": 0.5,
            "camera_status": "ONLINE",
            "plc_status": "ONLINE",
            "clock_offset_ms": 0.0,
        }
        self.service.send_heartbeat(device_id="device-1", payload=payload)
        call = next(call for call in self.client.calls if call[0] == "heartbeat")
        self.assertTrue(call[2].startswith("device-1:heartbeat:request-"))
        self.assertEqual(payload, call[4])

    def test_backoff_sequence_and_jitter_are_deterministic_when_injected(self):
        policy = BackoffPolicy(
            jitter_ratio=0.1,
            random_source=random.Random(7),
        )
        values = [policy.delay_seconds(index) for index in range(7)]
        self.assertEqual(7, len(values))
        self.assertTrue(0.9 <= values[0] <= 1.1)
        self.assertTrue(810 <= values[-1] <= 990)

    def test_retry_after_is_a_floor_with_default_jitter(self):
        policy = BackoffPolicy(random_source=random.Random(1))
        delay = policy.delay_seconds(0, retry_after_seconds=10)
        self.assertEqual(10, delay)


if __name__ == "__main__":
    unittest.main()
