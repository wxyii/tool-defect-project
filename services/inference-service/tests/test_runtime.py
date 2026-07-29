import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
SERVICE_SRC = PROJECT_ROOT / "services/inference-service/src"
for path in (SRC_ROOT, SERVICE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from inference_service.api.health import RuntimeHealthService
from inference_service.model_runtime.slot import (
    RuntimeProfile,
    RuntimeSlot,
)
from inference_service.model_runtime.supervisor import RuntimeSupervisor
from inference_service.model_runtime.worker import (
    IsolationPolicy,
    ModelWorkerProcess,
    WorkerPluginSpec,
)
from inference_service.plugins.algorithms.polar_anomaly import (
    PolarAnomalyAdapter,
)
from tool_defect.models.package import (
    ModelInputSpec,
    ModelManifest,
    PreprocessorRequirement,
    VerifiedModelPackage,
    file_sha256,
)
from tool_defect.plugin_api import (
    NeverCancelled,
    PluginError,
    PluginErrorCode,
    PluginState,
    PreparedBatch,
    QualityStatus,
    RuntimeContext,
    inconclusive_output,
)


class RuntimeSlotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.package = _package(self.root)
        self.profile = RuntimeProfile(
            device="cpu",
            concurrency=1,
            prefetch=1,
            memory_limit_mb=512,
            environment_lock_sha256="a" * 64,
            isolation_required=False,
        )

    async def asyncTearDown(self):
        self.temporary.cleanup()

    async def test_slot_is_not_ready_until_warmup_and_health_succeed(self):
        slot = RuntimeSlot("cpu-1", self.profile)
        self.assertFalse(slot.ready)
        plugin = _RuntimePlugin(healthy_after_warmup=False)

        with self.assertRaises(PluginError) as captured:
            await slot.load(self.package, plugin, _context(self.root))

        self.assertEqual(
            captured.exception.info.code,
            PluginErrorCode.MODEL_INCOMPATIBLE,
        )
        self.assertEqual(slot.state, PluginState.FAILED)
        self.assertTrue(plugin.closed)

    async def test_single_slot_serializes_parallel_requests(self):
        slot = RuntimeSlot("cpu-1", self.profile)
        plugin = _RuntimePlugin(delay=0.04)
        await slot.load(self.package, plugin, _context(self.root))

        await asyncio.gather(
            slot.execute(_prepared(), _context(self.root, run_id="run-1")),
            slot.execute(_prepared(), _context(self.root, run_id="run-2")),
            slot.execute(_prepared(), _context(self.root, run_id="run-3")),
        )

        self.assertEqual(slot.max_active, 1)
        self.assertEqual(plugin.max_active, 1)
        self.assertEqual(plugin.predict_calls, 3)
        await slot.close()
        self.assertEqual(slot.state, PluginState.CLOSED)

    async def test_close_waits_for_active_request_and_releases_plugin(self):
        slot = RuntimeSlot("cpu-1", self.profile)
        plugin = _RuntimePlugin(delay=0.08)
        await slot.load(self.package, plugin, _context(self.root))
        running = asyncio.create_task(
            slot.execute(_prepared(), _context(self.root))
        )
        await asyncio.sleep(0.01)

        await slot.close()
        await running

        self.assertTrue(plugin.closed)
        self.assertEqual(slot.state, PluginState.CLOSED)

    async def test_environment_lock_mismatch_blocks_loading(self):
        slot = RuntimeSlot(
            "cpu-1",
            RuntimeProfile(
                device="cpu",
                concurrency=1,
                prefetch=1,
                memory_limit_mb=512,
                environment_lock_sha256="b" * 64,
                isolation_required=False,
            ),
        )

        with self.assertRaises(PluginError):
            await slot.load(
                self.package, _RuntimePlugin(), _context(self.root)
            )

        self.assertEqual(slot.state, PluginState.DISCOVERED)

    async def test_production_profile_rejects_in_process_algorithm(self):
        profile = RuntimeProfile(
            device="cpu",
            concurrency=1,
            prefetch=1,
            memory_limit_mb=512,
            environment_lock_sha256="a" * 64,
        )
        slot = RuntimeSlot("cpu-1", profile)

        with self.assertRaises(PluginError) as captured:
            await slot.load(
                self.package, _RuntimePlugin(), _context(self.root)
            )

        self.assertEqual(
            captured.exception.info.code,
            PluginErrorCode.MODEL_INCOMPATIBLE,
        )
        self.assertEqual(slot.state, PluginState.DISCOVERED)

    async def test_supervisor_selects_exact_warmed_cpu_or_gpu_slot(self):
        cpu = RuntimeSlot("cpu-1", self.profile)
        gpu = RuntimeSlot(
            "gpu-1",
            RuntimeProfile(
                device="gpu",
                concurrency=1,
                prefetch=1,
                memory_limit_mb=2048,
                environment_lock_sha256="a" * 64,
                isolation_required=False,
            ),
        )
        await cpu.load(self.package, _RuntimePlugin(), _context(self.root))
        gpu_context = _context(self.root, device="gpu")
        await gpu.load(self.package, _RuntimePlugin(), gpu_context)
        supervisor = RuntimeSupervisor((cpu, gpu))

        selected = supervisor.resolve(
            self.package.manifest.model_version,
            self.package.package_sha256,
            "gpu",
        )

        self.assertIs(selected, gpu)
        with self.assertRaises(PluginError):
            supervisor.resolve(
                "other-version",
                self.package.package_sha256,
                "gpu",
            )
        health = RuntimeHealthService(
            supervisor, runtime_version="1.0.0"
        )
        self.assertEqual(
            health.readiness(),
            {"ready": True, "runtime_version": "1.0.0"},
        )
        for model in health.models()["models"]:
            self.assertEqual(
                set(model), {"model_version", "sha256", "ready"}
            )
        await supervisor.close()


class IsolationPolicyTests(unittest.TestCase):
    def test_worker_environment_removes_credentials_and_blocks_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            policy = IsolationPolicy(
                allowed_environment=("SAFE_SETTING", "API_TOKEN"),
                temp_dir=root,
                memory_limit_mb=512,
                cpu_time_seconds=30,
            )
            with mock.patch.dict(
                os.environ,
                {
                    "SAFE_SETTING": "enabled",
                    "API_TOKEN": "must-not-leak",
                    "DATABASE_URL": "must-not-leak",
                },
                clear=True,
            ):
                sanitized = policy.sanitized_environment()

            self.assertEqual(sanitized, {"SAFE_SETTING": "enabled"})
            self.assertFalse(policy.network_enabled)

    def test_worker_loads_and_warms_model_without_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package = _isolated_package(root / "package")
            policy = IsolationPolicy(
                allowed_environment=("SAFE_SETTING", "API_TOKEN"),
                temp_dir=root / "worker",
                memory_limit_mb=2048,
                cpu_time_seconds=30,
            )
            worker = ModelWorkerProcess(
                policy,
                WorkerPluginSpec.from_plugin_class(
                    PolarAnomalyAdapter
                ),
                startup_timeout_seconds=30,
            )
            try:
                with mock.patch.dict(
                    os.environ,
                    {
                        "SAFE_SETTING": "enabled",
                        "API_TOKEN": "must-not-leak",
                    },
                    clear=True,
                ):
                    worker.load(package, _context(root))
                worker.warmup()

                self.assertTrue(worker.health()["ready"])
                environment_keys = worker.environment_keys()
                self.assertIn("SAFE_SETTING", environment_keys)
                self.assertNotIn("API_TOKEN", environment_keys)
                self.assertFalse(
                    any(
                        marker in key.upper()
                        for key in environment_keys
                        for marker in (
                            "PASSWORD",
                            "SECRET",
                            "CREDENTIAL",
                            "DATABASE",
                            "RABBIT",
                            "AWS_",
                            "S3_",
                        )
                    )
                )
                isolation = worker.isolation_status()
                self.assertTrue(isolation["network_blocked"])
                self.assertFalse(isolation["network_enabled"])
                self.assertEqual(isolation["memory_limit_mb"], 2048)
                try:
                    output = worker.predict(
                        _polar_prepared(), _context(root)
                    )
                except PluginError as error:
                    self.assertEqual(
                        error.info.code,
                        PluginErrorCode.PREPROCESS_REJECTED,
                    )
                else:
                    self.assertIn(
                        output.outcome.value,
                        {
                            "QUALIFIED",
                            "UNQUALIFIED",
                            "INCONCLUSIVE",
                        },
                    )
            finally:
                worker.close()
            self.assertFalse(worker.alive)

    def test_worker_timeout_destroys_process_before_next_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            worker = ModelWorkerProcess(
                IsolationPolicy(
                    allowed_environment=(),
                    temp_dir=Path(temporary).resolve(),
                ),
                WorkerPluginSpec.from_plugin_class(
                    PolarAnomalyAdapter
                ),
            )
            process = mock.Mock()
            process.is_alive.return_value = True
            parent = mock.Mock()
            parent.poll.return_value = False
            worker._process = process
            worker._parent = parent
            worker._loaded = True

            with self.assertRaises(PluginError) as captured:
                worker._request(
                    {"command": "PING"},
                    timeout=0.001,
                    stage="runtime_slot",
                )

            self.assertEqual(
                captured.exception.info.code,
                PluginErrorCode.RUNTIME_TRANSIENT,
            )
            process.terminate.assert_called_once()
            self.assertFalse(worker._loaded)
            self.assertIsNone(worker._parent)


class _RuntimePlugin:
    def __init__(self, *, healthy_after_warmup=True, delay=0.0):
        self.healthy_after_warmup = healthy_after_warmup
        self.delay = delay
        self.loaded = False
        self.warmed = False
        self.closed = False
        self.predict_calls = 0
        self.active = 0
        self.max_active = 0
        self.guard = threading.Lock()

    def load(self, package, context):
        context.cancellation.raise_if_cancelled()
        self.loaded = True

    def warmup(self):
        self.warmed = True

    def predict(self, prepared, context):
        with self.guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.predict_calls += 1
            time.sleep(self.delay)
            return inconclusive_output("TEST_ONLY")
        finally:
            with self.guard:
                self.active -= 1

    def health(self):
        return {
            "ready": bool(
                self.loaded
                and self.warmed
                and self.healthy_after_warmup
                and not self.closed
            )
        }

    def close(self):
        self.closed = True


def _prepared():
    return PreparedBatch(
        tensors={
            "model_input": np.zeros((1, 2, 2, 3), dtype=np.float32)
        },
        coordinate_spaces={
            "model_input": {
                "name": "model_input",
                "shape": [2, 2],
            }
        },
        transforms=(),
        artifacts={},
        quality_status=QualityStatus.OK,
        warnings=(),
        metadata={},
    )


def _polar_prepared():
    return PreparedBatch(
        tensors={
            "polar_denoised": np.zeros(
                (32, 64, 3), dtype=np.uint8
            )
        },
        coordinate_spaces={
            "polar_denoised": {
                "name": "polar_normalized",
                "shape": [32, 64],
            }
        },
        transforms=(),
        artifacts={
            "raw_outer_boundary": np.ones(64, dtype=np.float32),
            "outer_boundary": np.ones(64, dtype=np.float32),
        },
        quality_status=QualityStatus.OK,
        warnings=(),
        metadata={},
    )


def _context(root, *, run_id="run-1", device="cpu"):
    return RuntimeContext(
        run_id=run_id,
        attempt_id="attempt-1",
        pipeline_version="pipeline-1",
        config_sha256="sha256:" + "c" * 64,
        code_signature="runtime:test",
        runtime_slot_id=f"{device}-1",
        device=device,
        temp_dir=Path(root).resolve(),
        random_seed=0,
        deadline_monotonic=time.monotonic() + 60,
        cancellation=NeverCancelled(),
    )


def _package(root):
    manifest = ModelManifest(
        model_name="multitask",
        model_version="1",
        framework="tensorflow",
        framework_version="2.13.0",
        keras_version="2.13.1",
        python_version="3.11",
        input_spec=ModelInputSpec(
            shape=(2, 2, 3),
            dtype="float32",
            color_space="RGB",
            value_range=(0.0, 1.0),
        ),
        output_names=("cla_out", "seg_out"),
        label_map={0: "qualified", 1: "unqualified"},
        preprocessor=PreprocessorRequirement(
            plugin_id="tool-defect.basic-gray-resize",
            plugin_version="1.0.0",
            config_sha256="sha256:" + "d" * 64,
        ),
        dataset_version="dataset/1",
        source_run_id="run-1",
    )
    return VerifiedModelPackage(
        root=Path(root),
        manifest=manifest,
        package_sha256="e" * 64,
        file_sha256={"environment.lock": "a" * 64},
        signer_key_id="key-1",
        verification_report={"status": "VERIFIED"},
    )


def _isolated_package(root):
    package_root = Path(root)
    package_root.mkdir(parents=True)
    model_path = package_root / "model.json"
    model_payload = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/polar_anomaly/polar_anomaly.json"
        ).read_text(encoding="utf-8")
    )
    model_payload["version"] = 2
    model_path.write_text(
        json.dumps(model_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    environment_path = package_root / "environment.lock"
    environment_path.write_text(
        "python==3.11\nnumpy==1.26.4\n",
        encoding="utf-8",
    )
    checksums_path = package_root / "checksums.sha256"
    checksums_path.write_text(
        f"{file_sha256(model_path)}  model.json\n"
        f"{file_sha256(environment_path)}  environment.lock\n",
        encoding="utf-8",
    )
    (package_root / "signature.sig").write_text(
        "{}\n", encoding="utf-8"
    )
    base = _package(package_root)
    return VerifiedModelPackage(
        root=package_root.resolve(),
        manifest=base.manifest,
        package_sha256=file_sha256(checksums_path),
        file_sha256={
            "model.json": file_sha256(model_path),
            "environment.lock": file_sha256(environment_path),
        },
        signer_key_id="key-1",
        verification_report={
            "status": "VERIFIED",
            "model_name": base.manifest.model_name,
            "model_version": base.manifest.model_version,
            "package_sha256": file_sha256(checksums_path),
            "signer_key_id": "key-1",
            "verified_files": ["environment.lock", "model.json"],
        },
    )


if __name__ == "__main__":
    unittest.main()
