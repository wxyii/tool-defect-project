import hashlib
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
for source in (
    ROOT / "src",
    ROOT / "apps/edge-agent/src",
    ROOT / "services/inference-service/src",
):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from edge_agent.capture.models import CapturedFrame
from edge_agent.capture.storage import AtomicCaptureStore
from edge_agent.local_queue.database import EdgeQueue
from edge_agent.local_queue.models import LocalCaptureState
from edge_agent.sync.backoff import BackoffPolicy
from edge_agent.sync.client import (
    CaptureInitialization,
    CentralCapture,
    DetectionSubmission,
    SyncService,
    UploadTicket,
)
from inference_service.clients.business_api import CallbackAcceptance
from inference_service.orchestration.decoder import ImageDecoder
from inference_service.orchestration.pipeline import (
    InferenceOrchestrator,
    InferenceTask,
)
from inference_service.storage.materializer import (
    ObjectMaterializer,
    ObjectReference,
)
from tool_defect.plugin_api import (
    AlgorithmOutcome,
    AlgorithmOutput,
    ApiVersion,
    PluginDescriptor,
    PluginKind,
    PreparedBatch,
    QualityStatus,
)


CAPTURE_ID = "019f0000-0000-7000-8000-000000000001"
TASK_ID = "019f0000-0000-7000-8000-000000000002"
ATTEMPT_ID = "019f0000-0000-7000-8000-000000000003"
MESSAGE_ID = "019f0000-0000-7000-8000-000000000020"
IMAGE_ID = "019f0000-0000-7000-8000-000000000022"
TRACEPARENT = (
    "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
)


class AutomaticDetectionEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clock = _Clock()
        self.backend = _VerticalBackend(self.clock)
        self.queue = EdgeQueue(
            self.root / "edge-queue.sqlite3",
            clock=self.clock,
        )
        self.store = AtomicCaptureStore(self.root / "edge", self.queue)
        self.image = _png()
        self.store.persist(
            capture_id=CAPTURE_ID,
            station_id="station-1",
            recipe_id="recipe-1",
            client_sequence=1,
            occurred_at="2026-07-30T01:00:00Z",
            frames=(
                CapturedFrame(
                    "PRIMARY",
                    self.image,
                    width=4,
                    height=3,
                ),
            ),
            trigger_id="plc-1",
            trigger_source="PLC",
        )
        self.final_results = []
        self.sync = SyncService(
            queue=self.queue,
            client=self.backend,
            data_root=self.root / "edge",
            backoff=BackoffPolicy(jitter_ratio=0),
            clock=self.clock,
            request_id_factory=_RequestIds(),
            final_result_handler=self.final_results.append,
            confirmed_handler=self.store.mark_confirmed,
        )

    async def asyncTearDown(self):
        self.queue.close()
        self.temporary.cleanup()

    async def test_normal_qualified_path_is_traceable_under_one_capture(self):
        self._sync_to_waiting()
        runtime = await self._infer(_output("qualified"))
        self._finish_edge()

        self.assertEqual(1, runtime.execute_calls)
        self.assertEqual("PASS", self.final_results[0].business_disposition)
        self._assert_single_business_fact("PASS")

    async def test_normal_unqualified_path_is_traceable_under_one_capture(self):
        self._sync_to_waiting()
        runtime = await self._infer(_output("unqualified"))
        self._finish_edge()

        self.assertEqual(1, runtime.execute_calls)
        self.assertEqual("FAIL", self.final_results[0].business_disposition)
        self._assert_single_business_fact("FAIL")

    async def test_empty_mask_contradiction_enters_hold_and_review(self):
        self._sync_to_waiting()
        await self._infer(_output("empty-mask"))
        self._finish_edge()

        self.assertEqual("HOLD", self.final_results[0].business_disposition)
        self.assertEqual(1, self.backend.review_placeholders)
        self._assert_single_business_fact("HOLD")

    async def test_corrupted_image_is_a_failure_and_never_passes(self):
        self._sync_to_waiting()
        acceptance, runtime = await self._execute(
            _output("qualified"),
            corrupt_download=True,
        )
        self._finish_edge()

        self.assertTrue(acceptance.failure)
        self.assertEqual(0, runtime.execute_calls)
        self.assertEqual("HOLD", self.final_results[0].business_disposition)
        self.assertEqual(0, len(self.backend.results))
        self.assertEqual(1, len(self.backend.failures))

    async def test_offline_capture_catches_up_without_duplicate_central_fact(self):
        self.backend.offline = True
        first = self.sync.run_once()
        self.assertEqual([CAPTURE_ID], first["retried"])
        self.assertEqual(
            LocalCaptureState.RETRY_WAIT,
            self.queue.get_capture(CAPTURE_ID).state,
        )

        self.backend.offline = False
        self.clock.value = self.queue.get_capture(CAPTURE_ID).retry_at
        self._sync_to_waiting()
        await self._infer(_output("qualified"))
        self._finish_edge()

        self.assertEqual(1, len(self.backend.captures))
        self.assertEqual(1, len(self.backend.tasks))
        self._assert_single_business_fact("PASS")

    async def test_duplicate_message_replays_same_hash_without_reinference(self):
        self._sync_to_waiting()
        orchestrator, runtime = self._orchestrator(_output("qualified"))

        first = await orchestrator.execute(self._task())
        second = await orchestrator.execute(self._task())
        self._finish_edge()

        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertEqual(first.result_sha256, second.result_sha256)
        self.assertEqual(1, runtime.execute_calls)
        self.assertEqual(1, self.backend.result_callbacks)
        self._assert_single_business_fact("PASS")

    async def test_process_crash_after_acceptance_replays_journal_only(self):
        self._sync_to_waiting()
        self.backend.raise_after_first_result = True
        first_orchestrator, first_runtime = self._orchestrator(
            _output("qualified")
        )

        first = await first_orchestrator.execute(self._task())
        restarted, restarted_runtime = self._orchestrator(
            _output("qualified")
        )
        second = await restarted.execute(self._task())
        self._finish_edge()

        self.assertFalse(first.accepted)
        self.assertTrue(second.accepted)
        self.assertEqual(first.result_sha256, second.result_sha256)
        self.assertEqual(1, first_runtime.execute_calls)
        self.assertEqual(0, restarted_runtime.execute_calls)
        self._assert_single_business_fact("PASS")

    async def test_model_version_lock_mismatch_is_hold_without_plugin_run(self):
        self._sync_to_waiting()
        acceptance, runtime = await self._execute(
            _output("qualified"),
            model_version="model-2",
        )
        self._finish_edge()

        self.assertTrue(acceptance.failure)
        self.assertEqual(0, runtime.execute_calls)
        self.assertEqual("HOLD", self.final_results[0].business_disposition)
        self.assertEqual(1, len(self.backend.failures))

    def _sync_to_waiting(self):
        for _ in range(4):
            self.sync.run_once()
        record = self.queue.get_capture(CAPTURE_ID)
        self.assertEqual(
            LocalCaptureState.WAIT_RESULT,
            record.state,
            f"state={record.state.value}, error={record.error_code}",
        )

    def _finish_edge(self):
        record = self.queue.get_capture(CAPTURE_ID)
        self.clock.value = record.next_poll_at
        self.sync.run_once()
        self.assertEqual(
            LocalCaptureState.DONE,
            self.queue.get_capture(CAPTURE_ID).state,
        )
        self.assertEqual(CAPTURE_ID, self.final_results[0].capture_id)

    async def _infer(self, output):
        acceptance, runtime = await self._execute(output)
        self.assertTrue(acceptance.accepted)
        self.assertFalse(acceptance.failure)
        return runtime

    async def _execute(
        self,
        output,
        *,
        corrupt_download=False,
        model_version="model-1",
    ):
        orchestrator, runtime = self._orchestrator(
            output,
            corrupt_download=corrupt_download,
        )
        acceptance = await orchestrator.execute(
            self._task(model_version=model_version)
        )
        return acceptance, runtime

    def _orchestrator(self, output, *, corrupt_download=False):
        runtime = _OutputRuntime(output)
        reader = _Reader(
            self.backend.uploaded_image,
            corrupt=corrupt_download,
        )
        orchestrator = InferenceOrchestrator(
            materializer=ObjectMaterializer(reader),
            decoder=ImageDecoder(),
            preprocessor=_Preprocessor(),
            runtime_slot=runtime,
            callback=self.backend,
            artifact_publisher=_Publisher(),
            runtime_id="runtime-1",
            runtime_version="1.0.0",
            temp_root=self.root / "inference",
        )
        return orchestrator, runtime

    def _task(self, *, model_version="model-1"):
        payload = self.backend.uploaded_image
        return InferenceTask(
            message_id=MESSAGE_ID,
            occurred_at="2026-07-30T01:00:01Z",
            traceparent=TRACEPARENT,
            detection_task_id=TASK_ID,
            capture_id=CAPTURE_ID,
            pipeline_id="019f0000-0000-7000-8000-000000000021",
            recipe_id="019f0000-0000-7000-8000-000000000099",
            pipeline_version="pipeline-1",
            pipeline_config_sha256="sha256:" + "4" * 64,
            preprocessor_version="tool-defect.e2e-preprocessor/1.0.0",
            algorithm_version="tool-defect.e2e-algorithm/1.0.0",
            model_version=model_version,
            model_sha256="sha256:" + "1" * 64,
            images=(
                ObjectReference(
                    image_id=IMAGE_ID,
                    object_key="captures/primary.png",
                    sha256=hashlib.sha256(payload).hexdigest(),
                    media_type="image/png",
                    size_bytes=len(payload),
                    width=4,
                    height=3,
                    image_role="PRIMARY",
                ),
            ),
            deadline_monotonic=time.monotonic() + 60,
        )

    def _assert_single_business_fact(self, disposition):
        self.assertEqual({CAPTURE_ID}, set(self.backend.captures))
        self.assertEqual({CAPTURE_ID}, set(self.backend.tasks))
        self.assertEqual(1, len(self.backend.results))
        self.assertEqual(CAPTURE_ID, self.backend.results[0]["capture_id"])
        self.assertEqual(disposition, self.backend.dispositions[CAPTURE_ID])


class _Clock:
    def __init__(self):
        self.value = 1_000.0

    def __call__(self):
        return self.value


class _RequestIds:
    def __init__(self):
        self.value = 0

    def __call__(self):
        self.value += 1
        return f"request-{self.value}"


class _VerticalBackend:
    def __init__(self, clock):
        self.clock = clock
        self.offline = False
        self.captures = {}
        self.tasks = {}
        self.uploaded_image = b""
        self.results = []
        self.failures = []
        self.dispositions = {}
        self.result_hashes = {}
        self.review_placeholders = 0
        self.result_callbacks = 0
        self.raise_after_first_result = False

    def initialize_capture(
        self, *, capture, images, idempotency_key, request_id
    ):
        if self.offline:
            raise TimeoutError("中心暂时不可达")
        self.captures.setdefault(capture.capture_id, "UPLOADING")
        return CaptureInitialization(
            capture_id=capture.capture_id,
            central_status="UPLOADING",
            upload_tickets=(
                UploadTicket(
                    image_id=IMAGE_ID,
                    image_role=images[0].image_role,
                    url="https://upload.invalid/e2e",
                    method="PUT",
                    headers={"Content-Type": "image/png"},
                    expires_at=self.clock() + 300,
                ),
            ),
        )

    def renew_upload_ticket(
        self, *, capture_id, image, idempotency_key, request_id
    ):
        return UploadTicket(
            image_id=IMAGE_ID,
            image_role=image.image_role,
            url="https://upload.invalid/e2e-renewed",
            method="PUT",
            headers={"Content-Type": "image/png"},
            expires_at=self.clock() + 300,
        )

    def upload_image(self, *, ticket, file_path, sha256, size_bytes):
        payload = file_path.read_bytes()
        if (
            len(payload) != size_bytes
            or hashlib.sha256(payload).hexdigest() != sha256
        ):
            raise AssertionError("采集端上传事实与本地清单不一致")
        self.uploaded_image = payload
        return "etag-e2e"

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
        if (
            image_id != IMAGE_ID
            or not upload_receipt
            or len(self.uploaded_image) != size_bytes
            or hashlib.sha256(self.uploaded_image).hexdigest() != sha256
        ):
            raise AssertionError("中心图片确认未满足完整性条件")
        self.captures[capture_id] = "READY"

    def submit_detection(
        self, *, capture_id, idempotency_key, request_id
    ):
        if self.captures.get(capture_id) != "READY":
            raise AssertionError("未 READY 的采集不能提交检测")
        self.tasks.setdefault(capture_id, TASK_ID)
        self.captures[capture_id] = "SUBMITTED"
        return DetectionSubmission(
            capture_id=capture_id,
            detection_task_id=TASK_ID,
            pipeline_version="pipeline-1",
            poll_after_ms=100,
        )

    def get_capture(self, *, capture_id, request_id):
        disposition = self.dispositions.get(capture_id)
        if disposition is None:
            return CentralCapture(capture_id, "PROCESSING", None, 1)
        return CentralCapture(capture_id, "FINALIZED", disposition, 0)

    def reconcile_captures(self, *, capture_ids, request_id):
        return [
            self.get_capture(capture_id=value, request_id=request_id)
            for value in capture_ids
            if value in self.captures
        ]

    def send_heartbeat(self, **kwargs):
        return None

    async def create_attempt(
        self,
        detection_task_id,
        message_id,
        worker_id,
        runtime_version,
        model_sha256,
        traceparent,
    ):
        if (
            detection_task_id != TASK_ID
            or self.tasks.get(CAPTURE_ID) != TASK_ID
            or model_sha256.removeprefix("sha256:") != "1" * 64
        ):
            raise AssertionError("执行尝试偏离任务锁定的模型事实")
        return ATTEMPT_ID

    async def put_result(
        self, attempt_id, payload, result_sha256, traceparent
    ):
        self.result_callbacks += 1
        existing = self.result_hashes.get(attempt_id)
        if existing is not None:
            if existing != result_sha256:
                raise AssertionError("同一尝试出现不同结果摘要")
            return CallbackAcceptance(True, result_sha256)

        self.result_hashes[attempt_id] = result_sha256
        self.results.append(dict(payload))
        outcome = payload["algorithm_outcome"]
        preprocess = payload["preprocess"]["quality_status"]
        if preprocess != "OK" or outcome == "INCONCLUSIVE":
            disposition = "HOLD"
        elif outcome == "QUALIFIED":
            disposition = "PASS" if not payload["regions"] else "HOLD"
        else:
            has_mask = any(
                item["kind"] == "DEFECT_MASK"
                for item in payload["artifacts"]
            )
            disposition = (
                "FAIL" if payload["regions"] and has_mask else "HOLD"
            )
        self.dispositions[payload["capture_id"]] = disposition
        self.captures[payload["capture_id"]] = "FINALIZED"
        if disposition == "HOLD":
            self.review_placeholders += 1
        if self.raise_after_first_result:
            self.raise_after_first_result = False
            raise TimeoutError("结果已接受，但响应在进程崩溃前丢失")
        return CallbackAcceptance(True, result_sha256)

    async def put_failure(self, attempt_id, error, traceparent):
        digest = hashlib.sha256(
            f"{error.code.value}:{error.stage}".encode("utf-8")
        ).hexdigest()
        if not self.failures:
            self.failures.append(error)
            self.dispositions[CAPTURE_ID] = "HOLD"
            self.captures[CAPTURE_ID] = "FINALIZED"
            self.review_placeholders += 1
        return CallbackAcceptance(True, digest)


class _Reader:
    def __init__(self, payload, *, corrupt=False):
        self.payload = payload
        self.corrupt = corrupt

    async def download(self, reference, destination):
        payload = self.payload
        if self.corrupt:
            payload = bytes((payload[0] ^ 0xFF,)) + payload[1:]
        destination.write_bytes(payload)


class _Preprocessor:
    descriptor = PluginDescriptor(
        plugin_id="tool-defect.e2e-preprocessor",
        plugin_kind=PluginKind.PREPROCESSOR,
        plugin_version="1.0.0",
        api_version=ApiVersion(1, 0),
        compatible_api_min=ApiVersion(1, 0),
        compatible_api_max=ApiVersion(2, 0),
        supported_tasks=("classification", "segmentation"),
        input_contract="frame-bundle/1.0",
        output_contract="prepared-batch/1.0",
        thread_safe=False,
        config_schema_id="e2e-preprocessor/1.0",
    )
    configuration_sha256 = "sha256:" + "6" * 64

    def prepare(self, frames, context):
        return PreparedBatch(
            tensors={"input": np.ones((1, 3, 4), dtype=np.float32)},
            coordinate_spaces={"input": {"name": "original"}},
            transforms=(),
            artifacts={},
            quality_status=QualityStatus.OK,
            warnings=(),
            metadata={},
        )


class _Profile:
    device = "cpu"


class _OutputRuntime:
    slot_id = "cpu-e2e"
    profile = _Profile()
    model_identity = ("model-1", "1" * 64)
    algorithm_descriptor = PluginDescriptor(
        plugin_id="tool-defect.e2e-algorithm",
        plugin_kind=PluginKind.ALGORITHM,
        plugin_version="1.0.0",
        api_version=ApiVersion(1, 0),
        compatible_api_min=ApiVersion(1, 0),
        compatible_api_max=ApiVersion(2, 0),
        supported_tasks=("classification", "segmentation"),
        input_contract="prepared-batch/1.0",
        output_contract="algorithm-output/1.0",
        thread_safe=False,
        config_schema_id="e2e-algorithm/1.0",
    )
    model_manifest = SimpleNamespace(
        preprocessor=SimpleNamespace(
            plugin_id=_Preprocessor.descriptor.plugin_id,
            plugin_version=_Preprocessor.descriptor.plugin_version,
            config_sha256=_Preprocessor.configuration_sha256,
        )
    )

    def __init__(self, output):
        self.output = output
        self.execute_calls = 0

    async def execute(self, prepared, context):
        self.execute_calls += 1
        return self.output


class _Publisher:
    async def publish(self, attempt_id, name, artifact):
        return {
            "kind": artifact.kind,
            "image_id": "019f0000-0000-7000-8000-000000000004",
            "object": {
                "bucket": "td-derived",
                "object_key": f"derived/{attempt_id}/{name}.png",
                "sha256": "2" * 64,
                "size_bytes": 10,
                "media_type": artifact.media_type,
            },
        }


def _output(kind):
    if kind == "qualified":
        return AlgorithmOutput(
            outcome=AlgorithmOutcome.QUALIFIED,
            class_probabilities={"qualified": 0.99, "unqualified": 0.01},
            masks={},
            regions=(),
            scores={},
            warnings=(),
            metadata={"mask_coordinate_spaces": {}},
        )
    mask = (
        np.zeros((3, 4), dtype=np.uint8)
        if kind == "empty-mask"
        else np.ones((3, 4), dtype=np.uint8)
    )
    regions = (
        ()
        if kind == "empty-mask"
        else (
            {
                "region_id": 1,
                "coordinate_space": "original",
                "geometry_type": "bbox",
                "geometry": {
                    "x": 0,
                    "y": 0,
                    "width": 2,
                    "height": 2,
                },
                "scores": {"defect": 0.98},
                "attributes": {},
            },
        )
    )
    return AlgorithmOutput(
        outcome=AlgorithmOutcome.UNQUALIFIED,
        class_probabilities={"qualified": 0.01, "unqualified": 0.99},
        masks={"defect": mask},
        regions=regions,
        scores={"defect": 0.99},
        warnings=(),
        metadata={"mask_coordinate_spaces": {"defect": "original"}},
    )


def _png():
    pixels = np.arange(36, dtype=np.uint8).reshape(3, 4, 3)
    success, encoded = cv2.imencode(".png", pixels)
    if not success:
        raise RuntimeError("无法生成端到端测试图片")
    return encoded.tobytes()


if __name__ == "__main__":
    unittest.main()
