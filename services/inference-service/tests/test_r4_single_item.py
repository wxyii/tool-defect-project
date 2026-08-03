import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
for source in (
    ROOT / "src",
    ROOT / "services/inference-service/src",
    ROOT / "tools/verify-contracts",
):
    sys.path.insert(0, str(source))

from inference_service.consumer.handler import SingleItemMessageHandler
from inference_service.orchestration.single_item import (
    AlgorithmResult,
    SingleItemOrchestrator,
    SingleItemTask,
)
from inference_service.orchestration.decoder import SingleImageDecoder
from inference_service.quality.checker import VersionedImageQualityChecker
from inference_service.storage.materializer import MaterializedObject, ObjectReference
from schema_engine import SchemaEngine


class R4QualityCheckerTests(unittest.TestCase):
    def setUp(self):
        self.checker = VersionedImageQualityChecker(
            minimum_laplacian_variance=5.0
        )

    def test_fixed_positive_sample_records_all_versioned_checks(self):
        image = _blade_image()
        result = self.checker.inspect(image)

        self.assertEqual(result.overall, "ACCEPTED")
        self.assertEqual(
            tuple(check.check_type for check in result.checks),
            ("DECODABLE", "BLADE_PRESENT", "BLADE_COMPLETE", "BLUR", "EXPOSURE"),
        )
        self.assertTrue(all(check.rule_id.startswith("quality-2.0.0/") for check in result.checks))

    def test_missing_blade_rejects_and_marks_remaining_checks_not_run(self):
        result = self.checker.inspect(np.full((256, 256, 3), 100, dtype=np.uint8))

        self.assertEqual(result.overall, "REJECTED")
        self.assertEqual(result.checks[1].reason_code, "BLADE_NOT_FOUND")
        self.assertTrue(all(check.status == "NOT_RUN" for check in result.checks[2:]))

    def test_decode_failure_is_not_quality_pass(self):
        result = self.checker.decode_failure()

        self.assertEqual(result.overall, "REJECTED")
        self.assertEqual(result.checks[0].status, "FAIL")
        self.assertTrue(all(check.status == "NOT_RUN" for check in result.checks[1:]))


class R4SingleItemOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    async def asyncTearDown(self):
        self.temporary.cleanup()

    def test_v2_event_accepts_one_image_and_rejects_multiview_field(self):
        payload = _request_payload()
        task = SingleItemTask.from_contract(payload)

        self.assertEqual(task.image.image_id, payload["batch_item_id"])
        self.assertIsNone(task.image.image_role)

        invalid = dict(payload)
        invalid["images"] = [invalid.pop("image")]
        with self.assertRaises(ValueError):
            SingleItemTask.from_contract(invalid)

    def test_single_image_decoder_does_not_introduce_view_semantics(self):
        path = self.root / "single.png"
        self.assertTrue(cv2.imwrite(str(path), _blade_image()))
        encoded = path.read_bytes()
        import hashlib
        reference = ObjectReference(
            image_id="20000000-0000-4000-8000-000000000001",
            bucket="manual-originals",
            object_key="manual-originals/r4/item.png",
            sha256=hashlib.sha256(encoded).hexdigest(),
            size_bytes=len(encoded),
            media_type="image/png",
        )

        frame = SingleImageDecoder().decode(
            MaterializedObject(reference, path, reference.sha256, len(encoded))
        )

        self.assertNotIn("image_role", frame.attributes)
        self.assertEqual(frame.attributes, {"image_kind": "RAW"})

    async def test_quality_rejection_skips_algorithm_and_publishes_contract_event(self):
        algorithm = _Algorithm()
        events = _Events()
        orchestrator = self._orchestrator(
            pixels=np.full((256, 256, 3), 100, dtype=np.uint8),
            algorithm=algorithm,
            events=events,
        )

        accepted = await orchestrator.execute(SingleItemTask.from_contract(_request_payload()))

        self.assertTrue(accepted)
        self.assertEqual(algorithm.calls, 0)
        self.assertEqual(events.completed["quality"]["overall"], "REJECTED")
        self.assertEqual(events.completed["algorithm_outcome"], "INCONCLUSIVE")
        _validate_event(events.completed, "InferenceItemCompleted")

    async def test_checker_exception_publishes_failure_and_does_not_ack_early(self):
        events = _Events()
        orchestrator = self._orchestrator(
            pixels=_blade_image(),
            algorithm=_Algorithm(),
            events=events,
            checker=_BrokenChecker(),
        )
        handler = SingleItemMessageHandler(orchestrator)
        delivery = _Delivery()

        handled = await handler.handle(_request_payload(), delivery)

        self.assertTrue(handled)
        self.assertEqual(delivery.acks, 1)
        self.assertIsNone(events.completed)
        self.assertEqual(events.failed["error_code"], "TD-INFERENCE-TECHNICAL-FAILED")
        _validate_event(events.failed, "InferenceItemFailed")

    async def test_success_evidence_contains_required_execution_metadata(self):
        events = _Events()
        artifacts = _Artifacts()
        orchestrator = self._orchestrator(
            pixels=_blade_image(),
            algorithm=_Algorithm(),
            events=events,
            artifacts=artifacts,
        )

        await orchestrator.execute(SingleItemTask.from_contract(_request_payload()))

        self.assertEqual(artifacts.value["model_version"], "model-r4")
        self.assertEqual(artifacts.value["pipeline_version"], "2.0.0")
        self.assertEqual(artifacts.value["defect_region_count"], 1)
        self.assertEqual(artifacts.value["inference_ms"], 7)
        self.assertEqual(events.completed["algorithm_outcome"], "UNQUALIFIED")

    async def test_duplicate_delivery_reuses_accepted_journal_without_rerunning(self):
        events = _Events()
        algorithm = _Algorithm()
        orchestrator = self._orchestrator(
            pixels=_blade_image(), algorithm=algorithm, events=events,
        )
        task = SingleItemTask.from_contract(_request_payload())

        self.assertTrue(await orchestrator.execute(task))
        self.assertTrue(await orchestrator.execute(task))

        self.assertEqual(algorithm.calls, 1)
        self.assertEqual(events.completed_calls, 1)

    def _orchestrator(self, *, pixels, algorithm, events, checker=None, artifacts=None):
        return SingleItemOrchestrator(
            materializer=_Materializer(),
            decoder=_Decoder(pixels),
            quality_checker=checker or VersionedImageQualityChecker(minimum_laplacian_variance=5.0),
            algorithm=algorithm,
            artifact_publisher=artifacts or _Artifacts(),
            event_publisher=events,
            temp_root=self.root,
        )


class _Materializer:
    async def materialize(self, reference, temp_dir):
        return object()


class _Frame:
    def __init__(self, pixels):
        self.pixels = pixels


class _Decoder:
    def __init__(self, pixels):
        self.pixels = pixels

    def decode(self, materialized):
        return _Frame(self.pixels)


class _Algorithm:
    def __init__(self):
        self.calls = 0

    async def infer(self, frame, pipeline_version):
        self.calls += 1
        return AlgorithmResult("UNQUALIFIED", 0.91, ({"x": 1},), "model-r4", 7)


class _BrokenChecker:
    checker_version = "quality-broken"

    def inspect(self, pixels):
        raise RuntimeError("内部细节不得进入安全消息")

    def decode_failure(self):
        raise AssertionError


class _Artifacts:
    def __init__(self):
        self.value = None

    async def publish(self, task, result):
        self.value = dict(result)
        encoded = json.dumps(result, sort_keys=True).encode()
        import hashlib
        return {
            "bucket": "model-evidence",
            "object_key": f"model-evidence/results/{task.batch_item_id}.json",
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "size_bytes": len(encoded),
            "media_type": "application/json",
        }


class _Events:
    def __init__(self):
        self.completed = None
        self.failed = None
        self.completed_calls = 0

    async def publish_completed(self, payload):
        self.completed_calls += 1
        self.completed = dict(payload)
        return True

    async def publish_failed(self, payload):
        self.failed = dict(payload)
        return True


class _Delivery:
    def __init__(self):
        self.acks = 0

    async def ack(self):
        self.acks += 1

    async def reject_to_dead_letter(self):
        raise AssertionError


def _blade_image():
    image = np.full((256, 256, 3), 80, dtype=np.uint8)
    cv2.circle(image, (128, 128), 82, (175, 175, 175), -1)
    for angle in range(0, 360, 20):
        radians = np.deg2rad(angle)
        start = (128 + int(25 * np.cos(radians)), 128 + int(25 * np.sin(radians)))
        end = (128 + int(75 * np.cos(radians)), 128 + int(75 * np.sin(radians)))
        cv2.line(image, start, end, (55, 55, 55), 2)
    return image


def _request_payload():
    return {
        "message_id": "10000000-0000-4000-8000-000000000001",
        "occurred_at": "2026-08-03T00:00:00Z",
        "idempotency_key": "idem-r4-request-0001",
        "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
        "batch_item_id": "20000000-0000-4000-8000-000000000001",
        "detection_task_id": "30000000-0000-4000-8000-000000000001",
        "image": {
            "bucket": "manual-originals",
            "object_key": "manual-originals/r4/item.png",
            "sha256": "a" * 64,
            "size_bytes": 1024,
            "media_type": "image/png",
        },
        "pipeline_version": "2.0.0",
    }


def _validate_event(payload, name):
    path = ROOT / "contracts/json-schema/event-payloads-v2.schema.json"
    engine = SchemaEngine()
    schema = engine.pointer(engine.load(path), f"/$defs/{name}")
    engine.validate(payload, schema, path.resolve(), "")
