import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
SERVICE_SRC = PROJECT_ROOT / "services/inference-service/src"
CONTRACT_TOOL_ROOT = PROJECT_ROOT / "tools/verify-contracts"
for path in (SRC_ROOT, SERVICE_SRC, CONTRACT_TOOL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from inference_service.clients.business_api import (
    CallbackAcceptance,
    StandardBusinessApiClient,
)
from inference_service.clients.canonical_json import (
    encode as canonical_json,
    sha256 as canonical_sha256,
)
from inference_service.consumer.handler import InferenceMessageHandler
from inference_service.orchestration.pipeline import (
    ExecutionAcceptance,
    InferenceOrchestrator,
    InferenceTask,
)
from inference_service.orchestration.result_journal import (
    FileResultJournal,
    PendingResult,
)
from inference_service.storage.materializer import ObjectReference
from schema_engine import SchemaEngine
from tool_defect.plugin_api import (
    FrameBundle,
    ImageFrame,
    ApiVersion,
    PluginDescriptor,
    PluginError,
    PluginErrorCode,
    PluginKind,
    PreparedBatch,
    QualityStatus,
)


class OrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    async def asyncTearDown(self):
        self.temporary.cleanup()

    async def test_rejected_preprocessing_skips_algorithm_and_cleans_temp(self):
        callback = _Callback()
        runtime = _RuntimeSlot()
        preprocessor = _RejectedPreprocessor()
        orchestrator = self._orchestrator(
            callback=callback,
            runtime=runtime,
            preprocessor=preprocessor,
        )

        acceptance = await orchestrator.execute(_task())

        self.assertTrue(acceptance.accepted)
        self.assertFalse(acceptance.failure)
        self.assertEqual(runtime.execute_calls, 0)
        self.assertEqual(
            callback.result_payload["algorithm_outcome"],
            "INCONCLUSIVE",
        )
        self.assertIn(
            "PREPROCESS_REJECTED",
            callback.result_payload["warnings"],
        )
        self.assertFalse(preprocessor.observed_temp_dir.exists())
        self._assert_only_callback_journal()

        SchemaEngine().validate_file(
            callback.result_payload,
            PROJECT_ROOT
            / "contracts/json-schema/detection-result-v1.schema.json",
        )
        self.assertAlmostEqual(
            sum(
                callback.result_payload[
                    "class_probabilities"
                ].values()
            ),
            1.0,
        )
        self.assertNotIn("pipeline_version", callback.result_payload)
        self.assertEqual(
            callback.result_payload["preprocess"]["config_sha256"],
            "6" * 64,
        )

    def test_frozen_contract_event_is_converted_without_field_drift(self):
        payload = json.loads(
            (
                PROJECT_ROOT
                / "contracts/examples/events/inference-task-v1.json"
            ).read_text(encoding="utf-8")
        )

        task = InferenceTask.from_contract(
            payload,
            recipe_id="019f0000-0000-7000-8000-000000000099",
            model_sha256="1" * 64,
            now_utc=datetime(
                2026, 7, 28, 10, 30, 2, tzinfo=timezone.utc
            ),
            now_monotonic=100.0,
        )

        self.assertEqual(task.deadline_monotonic, 108.0)
        self.assertEqual(
            task.preprocessor_version,
            payload["pipeline"]["preprocessor_version"],
        )
        self.assertEqual(task.images[0].bucket, "td-original")
        self.assertEqual(task.images[0].kind, "RAW")

    async def test_queue_ack_occurs_only_after_backend_accepts_result(self):
        events = []
        callback = _Callback(events=events)
        orchestrator = self._orchestrator(
            callback=callback,
            runtime=_RuntimeSlot(),
            preprocessor=_RejectedPreprocessor(),
        )
        handler = InferenceMessageHandler(orchestrator)
        delivery = _Delivery(events)

        handled = await handler.handle(_task(), delivery)

        self.assertTrue(handled)
        self.assertEqual(events[-2:], ["backend-result-accepted", "ack"])

    async def test_backend_rejection_leaves_queue_message_unacked(self):
        orchestrator = _AcceptanceOnlyOrchestrator(accepted=False)
        handler = InferenceMessageHandler(orchestrator)
        delivery = _Delivery([])

        handled = await handler.handle(_task(), delivery)

        self.assertFalse(handled)
        self.assertEqual(delivery.ack_calls, 0)

    async def test_unknown_result_callback_is_retried_without_failure_fact(self):
        callback = _ResultUnavailableCallback()
        orchestrator = self._orchestrator(
            callback=callback,
            runtime=_RuntimeSlot(),
            preprocessor=_RejectedPreprocessor(),
        )

        acceptance = await orchestrator.execute(_task())

        self.assertFalse(acceptance.accepted)
        self.assertFalse(acceptance.failure)
        self.assertEqual(callback.failure_calls, 0)
        self.assertIsNotNone(callback.result_payload)

    async def test_duplicate_message_replays_journal_without_rerunning_pipeline(
        self,
    ):
        callback = _OneShotUnavailableCallback()
        preprocessor = _RejectedPreprocessor()
        materializer = _Materializer()
        orchestrator = InferenceOrchestrator(
            materializer=materializer,
            decoder=_Decoder(),
            preprocessor=preprocessor,
            runtime_slot=_RuntimeSlot(),
            callback=callback,
            artifact_publisher=_Publisher(),
            runtime_id="runtime-1",
            runtime_version="1.0.0",
            temp_root=self.root,
        )

        first = await orchestrator.execute(_task())
        second = await orchestrator.execute(_task())
        third = await orchestrator.execute(_task())

        self.assertFalse(first.accepted)
        self.assertTrue(second.accepted)
        self.assertTrue(third.accepted)
        self.assertEqual(first.result_sha256, second.result_sha256)
        self.assertEqual(second.result_sha256, third.result_sha256)
        self.assertEqual(materializer.calls, 1)
        self.assertEqual(preprocessor.prepare_calls, 1)
        self.assertEqual(callback.result_calls, 2)
        self.assertEqual(callback.failure_calls, 0)
        self._assert_only_callback_journal()

    async def test_failure_is_reported_without_fabricated_result(self):
        callback = _Callback()
        orchestrator = self._orchestrator(
            callback=callback,
            runtime=_RuntimeSlot(
                model_identity=("different", "f" * 64)
            ),
            preprocessor=_RejectedPreprocessor(),
        )

        acceptance = await orchestrator.execute(_task())

        self.assertTrue(acceptance.failure)
        self.assertTrue(acceptance.accepted)
        self.assertIsNone(callback.result_payload)
        self.assertEqual(
            callback.failure_info.code.value,
            "MODEL_INCOMPATIBLE",
        )

    async def test_preprocessor_model_binding_mismatch_is_blocked(self):
        callback = _Callback()
        preprocessor = _RejectedPreprocessor()
        preprocessor.configuration_sha256 = "sha256:" + "9" * 64
        orchestrator = self._orchestrator(
            callback=callback,
            runtime=_RuntimeSlot(),
            preprocessor=preprocessor,
        )

        acceptance = await orchestrator.execute(_task())

        self.assertTrue(acceptance.failure)
        self.assertEqual(
            callback.failure_info.code.value,
            "MODEL_INCOMPATIBLE",
        )
        self.assertIsNone(callback.result_payload)

    def _orchestrator(self, *, callback, runtime, preprocessor):
        return InferenceOrchestrator(
            materializer=_Materializer(),
            decoder=_Decoder(),
            preprocessor=preprocessor,
            runtime_slot=runtime,
            callback=callback,
            artifact_publisher=_Publisher(),
            runtime_id="runtime-1",
            runtime_version="1.0.0",
            temp_root=self.root,
        )

    def _assert_only_callback_journal(self):
        entries = tuple(self.root.iterdir())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, ".callback-journal")
        self.assertEqual(len(tuple(entries[0].glob("*.json"))), 1)


class BusinessApiClientTests(unittest.IsolatedAsyncioTestCase):
    def test_canonical_json_matches_backend_number_and_unicode_rules(self):
        value = {"b": 1.2300, "a": -0.0, "text": "缺陷"}

        encoded = canonical_json(value)

        self.assertEqual(encoded, '{"a":0,"b":1.23,"text":"缺陷"}')
        self.assertEqual(
            canonical_sha256(value),
            "3edca27991c7b78eb2d56d5027eb7ca7d"
            "4d33861a34cf315c5af96a7943ed8c9",
        )

    async def test_concrete_client_uses_frozen_idempotent_callbacks(self):
        transport = _Transport()
        client = StandardBusinessApiClient(transport)
        task = _task()

        attempt_id = await client.create_attempt(
            task.detection_task_id,
            task.message_id,
            "worker-1",
            "1.0.0",
            task.model_sha256,
            task.traceparent,
        )
        result = await client.put_result(
            attempt_id,
            {"schema_version": "1.0"},
            "7" * 64,
            task.traceparent,
        )
        failure = await client.put_failure(
            attempt_id,
            PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "model_load",
                "模型不兼容",
            ).info,
            task.traceparent,
        )

        self.assertTrue(result.accepted)
        self.assertTrue(failure.accepted)
        self.assertEqual(len(transport.calls), 3)
        start = transport.calls[0]
        self.assertEqual(start["method"], "POST")
        self.assertEqual(
            start["payload"]["model_sha256"], "1" * 64
        )
        self.assertEqual(
            start["headers"]["Idempotency-Key"],
            task.message_id,
        )
        failure_call = transport.calls[2]
        self.assertEqual(
            failure_call["payload"]["error_code"],
            "TD-MODEL-INCOMPATIBLE-001",
        )
        self.assertEqual(
            failure_call["payload"]["stage"], "MODEL_LOAD"
        )


class ResultJournalTests(unittest.TestCase):
    def test_retention_prunes_only_old_accepted_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            journal = FileResultJournal(
                Path(temporary),
                maximum_accepted_entries=1,
            )
            pending = _pending_result("a")
            first_accepted = _pending_result("b")
            latest_accepted = _pending_result("c")

            journal.store(pending)
            journal.store(first_accepted)
            journal.mark_accepted(first_accepted.attempt_id)
            journal.store(latest_accepted)
            journal.mark_accepted(latest_accepted.attempt_id)

            self.assertIsNotNone(journal.load(pending.attempt_id))
            self.assertIsNone(journal.load(first_accepted.attempt_id))
            latest = journal.load(latest_accepted.attempt_id)
            self.assertIsNotNone(latest)
            self.assertTrue(latest.callback_accepted)


class _Materializer:
    def __init__(self):
        self.calls = 0

    async def materialize(self, reference, temp_dir):
        self.calls += 1
        path = temp_dir / "materialized.object"
        path.write_bytes(b"controlled")
        return SimpleMaterialized(reference, path)


class SimpleMaterialized:
    def __init__(self, reference, path):
        self.reference = reference
        self.path = path
        self.sha256 = reference.sha256


class _Decoder:
    def decode(self, materialized):
        pixels = np.zeros((2, 2, 3), dtype=np.uint8)
        return ImageFrame(
            image_id=materialized.reference.image_id,
            pixels=pixels,
            color_space="BGR",
            media_type="image/png",
            sha256=materialized.reference.sha256,
            original_height=2,
            original_width=2,
            attributes={"image_role": "primary"},
        )


class _RejectedPreprocessor:
    descriptor = PluginDescriptor(
        plugin_id="tool-defect.test-preprocessor",
        plugin_kind=PluginKind.PREPROCESSOR,
        plugin_version="1.0.0",
        api_version=ApiVersion(1, 0),
        compatible_api_min=ApiVersion(1, 0),
        compatible_api_max=ApiVersion(2, 0),
        supported_tasks=("classification",),
        input_contract="frame-bundle/1.0",
        output_contract="prepared-batch/1.0",
        thread_safe=False,
        config_schema_id="test-preprocessor/1.0",
    )
    configuration_sha256 = "sha256:" + "6" * 64

    def __init__(self):
        self.observed_temp_dir = Path("/")
        self.prepare_calls = 0

    def prepare(self, frames: FrameBundle, context):
        self.prepare_calls += 1
        self.observed_temp_dir = context.temp_dir
        return PreparedBatch(
            tensors={},
            coordinate_spaces={},
            transforms=(),
            artifacts={},
            quality_status=QualityStatus.REJECTED,
            warnings=("LOW_GEOMETRY_CONFIDENCE",),
            metadata={},
        )


class _Profile:
    device = "cpu"


class _RuntimeSlot:
    def __init__(
        self,
        *,
        model_identity=("model-1", "1" * 64),
    ):
        self.slot_id = "cpu-1"
        self.profile = _Profile()
        self.model_identity = model_identity
        self.execute_calls = 0
        self.algorithm_descriptor = PluginDescriptor(
            plugin_id="tool-defect.test-algorithm",
            plugin_kind=PluginKind.ALGORITHM,
            plugin_version="1.0.0",
            api_version=ApiVersion(1, 0),
            compatible_api_min=ApiVersion(1, 0),
            compatible_api_max=ApiVersion(2, 0),
            supported_tasks=("classification",),
            input_contract="prepared-batch/1.0",
            output_contract="algorithm-output/1.0",
            thread_safe=False,
            config_schema_id="test-algorithm/1.0",
        )
        self.model_manifest = SimpleNamespace(
            preprocessor=SimpleNamespace(
                plugin_id=_RejectedPreprocessor.descriptor.plugin_id,
                plugin_version=(
                    _RejectedPreprocessor.descriptor.plugin_version
                ),
                config_sha256=(
                    _RejectedPreprocessor.configuration_sha256
                ),
            )
        )

    async def execute(self, prepared, context):
        self.execute_calls += 1
        raise AssertionError("REJECTED 预处理不应执行算法")


class _Callback:
    def __init__(self, *, events=None):
        self.events = events if events is not None else []
        self.result_payload = None
        self.failure_info = None

    async def create_attempt(
        self,
        detection_task_id,
        message_id,
        runtime_id,
        runtime_version,
        model_sha256,
        traceparent,
    ):
        return "019f0000-0000-7000-8000-000000000003"

    async def put_result(
        self, attempt_id, payload, result_sha256, traceparent
    ):
        self.result_payload = dict(payload)
        self.events.append("backend-result-accepted")
        return CallbackAcceptance(
            accepted=True,
            result_sha256=result_sha256,
        )

    async def put_failure(self, attempt_id, error, traceparent):
        self.failure_info = error
        return CallbackAcceptance(
            accepted=True,
            result_sha256=hashlib.sha256(
                error.code.value.encode("utf-8")
            ).hexdigest(),
        )


class _ResultUnavailableCallback(_Callback):
    def __init__(self):
        super().__init__()
        self.failure_calls = 0

    async def put_result(
        self, attempt_id, payload, result_sha256, traceparent
    ):
        self.result_payload = dict(payload)
        raise TimeoutError("callback status unknown")

    async def put_failure(self, attempt_id, error, traceparent):
        self.failure_calls += 1
        return await super().put_failure(
            attempt_id, error, traceparent
        )


class _OneShotUnavailableCallback(_ResultUnavailableCallback):
    def __init__(self):
        super().__init__()
        self.result_calls = 0

    async def put_result(
        self, attempt_id, payload, result_sha256, traceparent
    ):
        self.result_calls += 1
        self.result_payload = dict(payload)
        if self.result_calls == 1:
            raise TimeoutError("callback status unknown")
        self.events.append("backend-result-accepted")
        return CallbackAcceptance(
            accepted=True,
            result_sha256=result_sha256,
        )


class _Publisher:
    async def publish(self, attempt_id, name, artifact):
        return {
            "kind": artifact.kind,
            "image_id": "019f0000-0000-7000-8000-000000000004",
            "object": {
                "bucket": "td-derived",
                "object_key": "derived/test.png",
                "sha256": "2" * 64,
                "size_bytes": 10,
                "media_type": artifact.media_type,
            },
        }


class _Delivery:
    def __init__(self, events):
        self.events = events
        self.ack_calls = 0

    async def ack(self):
        self.ack_calls += 1
        self.events.append("ack")

    async def reject_to_dead_letter(self):
        self.events.append("dead-letter")


class _AcceptanceOnlyOrchestrator:
    def __init__(self, *, accepted):
        self.accepted = accepted

    async def execute(self, task):
        return ExecutionAcceptance(
            accepted=self.accepted,
            attempt_id="attempt-1",
            result_sha256="3" * 64,
            failure=False,
        )


class _Transport:
    def __init__(self):
        self.calls = []

    async def request(
        self, method, path, *, headers, payload
    ):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "headers": dict(headers),
                "payload": dict(payload),
            }
        )
        if path.endswith("/attempts"):
            return {
                "attempt_id": (
                    "019f0000-0000-7000-8000-000000000003"
                ),
                "attempt_no": 1,
                "status": "RUNNING",
            }
        if path.endswith("/result"):
            return {
                "accepted": True,
                "result_sha256": headers["Idempotency-Key"],
            }
        return {
            "accepted": True,
            "request_id": "019f0000-0000-7000-8000-000000000005",
        }


def _task():
    return InferenceTask(
        message_id="019f0000-0000-7000-8000-000000000020",
        occurred_at="2026-07-29T00:00:00Z",
        traceparent=(
            "00-0123456789abcdef0123456789abcdef-"
            "0123456789abcdef-01"
        ),
        detection_task_id="019f0000-0000-7000-8000-000000000002",
        capture_id="019f0000-0000-7000-8000-000000000001",
        pipeline_id="019f0000-0000-7000-8000-000000000021",
        recipe_id="019f0000-0000-7000-8000-000000000099",
        pipeline_version="pipeline-1",
        pipeline_config_sha256="sha256:" + "4" * 64,
        preprocessor_version=(
            "tool-defect.test-preprocessor/1.0.0"
        ),
        algorithm_version="tool-defect.test-algorithm/1.0.0",
        model_version="model-1",
        model_sha256="sha256:" + "1" * 64,
        images=(
            ObjectReference(
                image_id="019f0000-0000-7000-8000-000000000022",
                object_key="captures/object.png",
                sha256="5" * 64,
                media_type="image/png",
                size_bytes=10,
            ),
        ),
        deadline_monotonic=time.monotonic() + 60,
    )


def _pending_result(suffix):
    task = _task()
    payload = {"schema_version": "1.0", "value": suffix}
    return PendingResult(
        attempt_id=(
            "019f0000-0000-7000-8000-00000000000" + suffix
        ),
        message_id=task.message_id,
        detection_task_id=task.detection_task_id,
        capture_id=task.capture_id,
        traceparent=task.traceparent,
        result_sha256=canonical_sha256(payload),
        payload=payload,
    )


if __name__ == "__main__":
    unittest.main()
