import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EDGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "packages/python-contracts/src"))
sys.path.insert(0, str(PROJECT_ROOT / "tools/verify-contracts"))
sys.path.insert(0, str(EDGE_ROOT / "src"))

from schema_engine import SchemaEngine
from verify_contracts import resolve_openapi
from tool_defect_contracts import CONTRACT_SOURCE_SHA256

from edge_agent.capture.models import CapturedFrame
from edge_agent.capture.storage import AtomicCaptureStore
from edge_agent.local_queue.database import EdgeQueue
from edge_agent.sync.generated_client import GeneratedClientAdapter
from device_fixtures import PNG
CAPTURE_ID = "019f0000-0000-7000-8000-000000000101"
STATION_ID = "019f0000-0000-7000-8000-000000000102"
RECIPE_ID = "019f0000-0000-7000-8000-000000000103"
IMAGE_ID = "019f0000-0000-7000-8000-000000000104"


class FakeGeneratedClient:
    contract_source_sha256 = CONTRACT_SOURCE_SHA256

    def __init__(self):
        self.calls = []
        self.ticket_upload_override = {}
        self.renewed_image_id = IMAGE_ID
        self.create_status = "UPLOADING"
        self.submit_status = "SUBMITTED"
        self.polled_capture_id = CAPTURE_ID
        self.heartbeat_request_id = (
            "019f0000-0000-7000-8000-000000000190"
        )

    def createCapture(self, request=None):
        self.calls.append(("createCapture", request))
        return {
            "capture_id": CAPTURE_ID,
            "status": self.create_status,
            "images": [self._ticket("initial")],
        }

    def renewCaptureImageUploadTicket(self, request=None):
        self.calls.append(("renewCaptureImageUploadTicket", request))
        ticket = self._ticket("renewed")
        ticket["image_id"] = self.renewed_image_id
        return ticket

    def completeCaptureImage(self, request=None):
        self.calls.append(("completeCaptureImage", request))
        return {
            "image_id": IMAGE_ID,
            "state": "AVAILABLE",
            "sha256": request["body"]["sha256"],
        }

    def submitCapture(self, request=None):
        self.calls.append(("submitCapture", request))
        return {
            "capture_id": CAPTURE_ID,
            "status": self.submit_status,
            "detection_task_id": "019f0000-0000-7000-8000-000000000105",
            "pipeline_version": "production-r8/12",
            "poll_after_ms": 500,
        }

    def getEdgeCapture(self, request=None):
        self.calls.append(("getEdgeCapture", request))
        response = self._central("PROCESSING", None)
        response["capture_id"] = self.polled_capture_id
        return response

    def queryCaptureSync(self, request=None):
        self.calls.append(("queryCaptureSync", request))
        return {"items": [self._central("FINALIZED", "PASS")]}

    def reportDeviceHeartbeat(self, request=None):
        self.calls.append(("reportDeviceHeartbeat", request))
        return {
            "accepted": True,
            "request_id": self.heartbeat_request_id,
        }

    def _ticket(self, label):
        upload = {
            "method": "PUT",
            "url": f"https://storage.example.invalid/{label}",
            "headers": {"Content-Type": "image/png"},
            "expires_at": "2026-07-29T02:00:00.000Z",
        }
        upload.update(self.ticket_upload_override)
        return {
            "image_id": IMAGE_ID,
            "upload": upload,
        }

    @staticmethod
    def _central(status, disposition):
        return {
            "capture_id": CAPTURE_ID,
            "capture_status": status,
            "business_disposition": disposition,
            "poll_after_ms": 500,
        }


class FakeObjectUploader:
    def __init__(self):
        self.calls = []

    def put(self, **kwargs):
        self.calls.append(kwargs)
        return "etag-opaque"


class GeneratedClientAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.queue = EdgeQueue(self.root / "edge_queue.sqlite3")
        AtomicCaptureStore(self.root, self.queue).persist(
            capture_id=CAPTURE_ID,
            station_id=STATION_ID,
            recipe_id=RECIPE_ID,
            client_sequence=123,
            occurred_at="2026-07-28T10:30:00.123Z",
            frames=[
                CapturedFrame(
                    "PRIMARY",
                    PNG,
                    width=32,
                    height=24,
                )
            ],
            trigger_id="plc-20260728-000123",
            trigger_source="PLC",
        )
        self.generated = FakeGeneratedClient()
        self.uploader = FakeObjectUploader()
        self.adapter = GeneratedClientAdapter(
            self.generated,
            object_uploader=self.uploader,
            expected_contract_sha256=CONTRACT_SOURCE_SHA256,
            clock=lambda: 1_000.0,
        )

    def tearDown(self):
        self.queue.close()
        self.temporary.cleanup()

    def test_create_request_uses_generated_operation_and_frozen_schema(self):
        capture = self.queue.get_capture(CAPTURE_ID)
        images = self.queue.list_images(CAPTURE_ID)
        response = self.adapter.initialize_capture(
            capture=capture,
            images=images,
            idempotency_key=f"{STATION_ID}:{CAPTURE_ID}:create",
            request_id="request-1",
        )
        self.assertEqual(CAPTURE_ID, response.capture_id)
        operation, request = self.generated.calls[0]
        self.assertEqual("createCapture", operation)
        self.assertEqual(
            f"{STATION_ID}:{CAPTURE_ID}:create",
            request["headers"]["Idempotency-Key"],
        )
        api_path = (
            PROJECT_ROOT
            / "contracts/openapi/tool-defect-api-v1.json"
        )
        api = json.loads(api_path.read_text(encoding="utf-8"))
        schema = resolve_openapi(
            api["components"]["schemas"]["CaptureCreateRequest"],
            api,
        )
        SchemaEngine().validate(request["body"], schema, api_path, "")

    def test_ticket_renewal_upload_confirmation_and_other_generated_operations(self):
        capture = self.queue.get_capture(CAPTURE_ID)
        image = self.queue.list_images(CAPTURE_ID)[0]
        self.queue.update_image_upload(
            capture_id=CAPTURE_ID,
            image_role="PRIMARY",
            status="PENDING",
            central_image_id=IMAGE_ID,
        )
        image = self.queue.list_images(CAPTURE_ID)[0]
        ticket = self.adapter.renew_upload_ticket(
            capture_id=CAPTURE_ID,
            image=image,
            idempotency_key="renew-key",
            request_id="request-2",
        )
        receipt = self.adapter.upload_image(
            ticket=ticket,
            file_path=self.root / image.relative_path,
            sha256=image.sha256,
            size_bytes=image.size_bytes,
        )
        self.adapter.complete_image(
            capture_id=CAPTURE_ID,
            image_id=IMAGE_ID,
            sha256=image.sha256,
            size_bytes=image.size_bytes,
            upload_receipt=receipt,
            idempotency_key="complete-key",
            request_id="request-3",
        )
        self.adapter.submit_detection(
            capture_id=capture.capture_id,
            idempotency_key="submit-key",
            request_id="request-4",
        )
        self.adapter.get_capture(
            capture_id=CAPTURE_ID,
            request_id="request-5",
        )
        items = self.adapter.reconcile_captures(
            capture_ids=[CAPTURE_ID],
            request_id="request-6",
        )
        self.assertEqual("PASS", items[0].business_disposition)
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
        self.adapter.send_heartbeat(
            device_id="019f0000-0000-7000-8000-000000000106",
            payload=payload,
            idempotency_key="heartbeat-key",
            request_id="request-7",
        )
        self.assertEqual(
            {
                "renewCaptureImageUploadTicket",
                "completeCaptureImage",
                "submitCapture",
                "getEdgeCapture",
                "queryCaptureSync",
                "reportDeviceHeartbeat",
            },
            {name for name, _ in self.generated.calls},
        )
        self.assertEqual("etag-opaque", receipt)
        self.assertEqual(1, len(self.uploader.calls))

    def test_contract_hash_mismatch_is_rejected_before_network_use(self):
        with self.assertRaisesRegex(ValueError, "契约哈希"):
            GeneratedClientAdapter(
                self.generated,
                object_uploader=self.uploader,
                expected_contract_sha256="0" * 64,
            )
        self.generated.contract_source_sha256 = "f" * 64
        with self.assertRaisesRegex(ValueError, "HTTP 传输"):
            GeneratedClientAdapter(
                self.generated,
                object_uploader=self.uploader,
                expected_contract_sha256=CONTRACT_SOURCE_SHA256,
            )

    def test_poll_response_capture_id_must_match_request(self):
        self.generated.polled_capture_id = (
            "019f0000-0000-7000-8000-000000000199"
        )
        with self.assertRaisesRegex(Exception, "capture_id"):
            self.adapter.get_capture(
                capture_id=CAPTURE_ID,
                request_id="request-wrong-capture",
            )

    def test_ticket_response_rejects_wrong_identity_or_unsafe_upload_target(self):
        image = self.queue.list_images(CAPTURE_ID)[0]
        self.queue.update_image_upload(
            capture_id=CAPTURE_ID,
            image_role="PRIMARY",
            status="PENDING",
            central_image_id=IMAGE_ID,
        )
        image = self.queue.list_images(CAPTURE_ID)[0]

        self.generated.renewed_image_id = (
            "019f0000-0000-7000-8000-000000000199"
        )
        with self.assertRaisesRegex(Exception, "不同的 image_id"):
            self.adapter.renew_upload_ticket(
                capture_id=CAPTURE_ID,
                image=image,
                idempotency_key="renew-key",
                request_id="request-wrong-id",
            )

        self.generated.renewed_image_id = IMAGE_ID
        invalid_uploads = (
            {"method": "DELETE"},
            {"url": "http://storage.example.invalid/plain"},
            {"url": "https://user:secret@storage.example.invalid/object"},
            {"headers": {f"X-Test-{index}": "x" for index in range(9)}},
        )
        for override in invalid_uploads:
            with self.subTest(override=override):
                self.generated.ticket_upload_override = override
                with self.assertRaises(Exception):
                    self.adapter.renew_upload_ticket(
                        capture_id=CAPTURE_ID,
                        image=image,
                        idempotency_key="renew-key",
                        request_id="request-unsafe",
                    )

    def test_frozen_response_constants_and_utc_timestamp_are_enforced(self):
        capture = self.queue.get_capture(CAPTURE_ID)
        images = self.queue.list_images(CAPTURE_ID)
        self.generated.create_status = "CREATED"
        with self.assertRaisesRegex(Exception, "UPLOADING"):
            self.adapter.initialize_capture(
                capture=capture,
                images=images,
                idempotency_key="create-key",
                request_id="request-create",
            )

        self.generated.create_status = "UPLOADING"
        self.generated.ticket_upload_override = {
            "expires_at": "2026-07-29T04:00:00+02:00"
        }
        with self.assertRaisesRegex(Exception, "UTC Z"):
            self.adapter.initialize_capture(
                capture=capture,
                images=images,
                idempotency_key="create-key",
                request_id="request-offset",
            )

        self.generated.ticket_upload_override = {}
        self.generated.submit_status = "PROCESSING"
        with self.assertRaisesRegex(Exception, "SUBMITTED"):
            self.adapter.submit_detection(
                capture_id=CAPTURE_ID,
                idempotency_key="submit-key",
                request_id="request-submit",
            )

        self.generated.heartbeat_request_id = "not-a-uuid"
        with self.assertRaisesRegex(Exception, "UUID"):
            self.adapter.send_heartbeat(
                device_id=STATION_ID,
                payload={"queue_depth": 0},
                idempotency_key="heartbeat-key",
                request_id="request-heartbeat",
            )


if __name__ == "__main__":
    unittest.main()
