"""单并发模型运行槽。"""

import asyncio
from dataclasses import dataclass
import re
from typing import Any, Mapping

from tool_defect.models.package import VerifiedModelPackage
from tool_defect.plugin_api import (
    AlgorithmOutput,
    PluginError,
    PluginErrorCode,
    PluginState,
    PreparedBatch,
    RuntimeContext,
    classify_unexpected,
    validate_algorithm_output,
)

from inference_service.model_runtime.worker import ModelWorkerProcess


_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


@dataclass(frozen=True)
class RuntimeProfile:
    device: str
    concurrency: int
    prefetch: int
    memory_limit_mb: int
    environment_lock_sha256: str
    isolation_required: bool = True

    def __post_init__(self) -> None:
        if self.device not in {"cpu", "gpu"}:
            raise ValueError("运行设备必须为 cpu 或 gpu")
        if self.concurrency != 1:
            raise ValueError("首版模型运行槽并发必须为 1")
        if self.prefetch != 1:
            raise ValueError("首版模型运行槽预取必须为 1")
        if (
            isinstance(self.memory_limit_mb, bool)
            or not isinstance(self.memory_limit_mb, int)
            or self.memory_limit_mb <= 0
            or not isinstance(self.environment_lock_sha256, str)
            or _SHA256.fullmatch(self.environment_lock_sha256) is None
        ):
            raise ValueError("运行槽资源限制和环境锁哈希不能为空")
        if not isinstance(self.isolation_required, bool):
            raise TypeError("运行槽隔离要求必须是布尔值")


class RuntimeSlot:
    def __init__(self, slot_id: str, profile: RuntimeProfile):
        if not slot_id:
            raise ValueError("运行槽标识不能为空")
        self.slot_id = slot_id
        self.profile = profile
        self.state = PluginState.DISCOVERED
        self._lock = asyncio.Lock()
        self._plugin: Any = None
        self._package: VerifiedModelPackage | None = None
        self._active = 0
        self._max_active = 0

    @property
    def ready(self) -> bool:
        return self.state == PluginState.READY

    @property
    def model_identity(self) -> tuple[str, str] | None:
        if self._package is None:
            return None
        return (
            self._package.manifest.model_version,
            self._package.package_sha256,
        )

    @property
    def model_manifest(self):
        return self._package.manifest if self._package is not None else None

    @property
    def algorithm_descriptor(self):
        return (
            getattr(self._plugin, "descriptor", None)
            if self._plugin is not None
            else None
        )

    @property
    def max_active(self) -> int:
        return self._max_active

    async def load(
        self,
        package: VerifiedModelPackage,
        plugin: Any,
        context: RuntimeContext,
    ) -> None:
        async with self._lock:
            if self.state not in {
                PluginState.DISCOVERED,
                PluginState.FAILED,
                PluginState.CLOSED,
            }:
                raise RuntimeError("运行槽当前状态不允许加载模型")
            if self.profile.isolation_required and not isinstance(
                plugin, ModelWorkerProcess
            ):
                raise PluginError.create(
                    PluginErrorCode.MODEL_INCOMPATIBLE,
                    "runtime_slot",
                    "生产运行槽只允许隔离模型工作进程",
                )
            environment_sha256 = package.file_sha256.get("environment.lock")
            expected_environment_sha256 = (
                self.profile.environment_lock_sha256.removeprefix("sha256:")
            )
            if environment_sha256 != expected_environment_sha256:
                raise PluginError.create(
                    PluginErrorCode.MODEL_INCOMPATIBLE,
                    "runtime_slot",
                    "模型环境锁与运行槽不一致",
                    {
                        "expected": expected_environment_sha256,
                        "actual": environment_sha256,
                    },
                )
            self.state = PluginState.ARTIFACT_VERIFIED
            self._plugin = plugin
            failure_stage = "model_load"
            try:
                await asyncio.to_thread(plugin.load, package, context)
                self.state = PluginState.LOADED
                failure_stage = "model_warmup"
                await asyncio.to_thread(plugin.warmup)
                self.state = PluginState.WARMED
                health = await asyncio.to_thread(plugin.health)
                if not bool(health.get("ready", False)):
                    raise PluginError.create(
                        PluginErrorCode.MODEL_INCOMPATIBLE,
                        "model_warmup",
                        "模型插件预热后未报告就绪",
                    )
            except Exception as error:
                self.state = PluginState.FAILED
                try:
                    await asyncio.to_thread(plugin.close)
                except Exception:
                    pass
                self._plugin = None
                self._package = None
                if isinstance(error, PluginError):
                    raise
                raise classify_unexpected(
                    error, failure_stage
                ) from error
            self._package = package
            self.state = PluginState.READY

    async def execute(
        self,
        prepared: PreparedBatch,
        context: RuntimeContext,
    ) -> AlgorithmOutput:
        if not self.ready:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "runtime_slot",
                "模型运行槽尚未就绪",
            )
        async with self._lock:
            if not self.ready:
                raise PluginError.create(
                    PluginErrorCode.MODEL_INCOMPATIBLE,
                    "runtime_slot",
                    "模型运行槽正在排空或已经失败",
                )
            context.cancellation.raise_if_cancelled()
            self._active += 1
            self._max_active = max(self._max_active, self._active)
            try:
                output = await asyncio.to_thread(
                    self._plugin.predict, prepared, context
                )
                validate_algorithm_output(output)
                return output
            except Exception as error:
                try:
                    healthy = bool(
                        (
                            await asyncio.to_thread(
                                self._plugin.health
                            )
                        ).get("ready", False)
                    )
                except Exception:
                    healthy = False
                if not healthy:
                    self.state = PluginState.FAILED
                    failed_plugin = self._plugin
                    self._plugin = None
                    self._package = None
                    try:
                        await asyncio.to_thread(
                            failed_plugin.close
                        )
                    except Exception:
                        pass
                if isinstance(error, PluginError):
                    raise
                raise classify_unexpected(
                    error, "inference"
                ) from error
            finally:
                self._active -= 1

    async def drain(self) -> None:
        if self.state == PluginState.READY:
            self.state = PluginState.DRAINING
        async with self._lock:
            return None

    async def close(self) -> None:
        if self.state == PluginState.CLOSED:
            return
        await self.drain()
        async with self._lock:
            plugin = self._plugin
            self._plugin = None
            self._package = None
            try:
                if plugin is not None:
                    await asyncio.to_thread(plugin.close)
            except Exception as error:
                raise classify_unexpected(
                    error, "plugin_close"
                ) from error
            finally:
                self.state = PluginState.CLOSED

    def health(self) -> Mapping[str, Any]:
        return {
            "slot_id": self.slot_id,
            "ready": self.ready,
            "state": self.state.value,
            "device": self.profile.device,
            "isolated": bool(
                isinstance(self._plugin, ModelWorkerProcess)
                if self._plugin is not None
                else self.profile.isolation_required
            ),
            "model_version": (
                self._package.manifest.model_version
                if self._package is not None
                else None
            ),
            "model_sha256": (
                self._package.package_sha256
                if self._package is not None
                else None
            ),
            "active": self._active,
        }
