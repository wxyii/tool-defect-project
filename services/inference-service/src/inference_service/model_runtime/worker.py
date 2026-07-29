"""无业务凭据、默认禁网且有资源上限的算法工作进程。"""

from dataclasses import dataclass
import importlib
import json
import multiprocessing
import os
from pathlib import Path
import time
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from tool_defect.models.package import (
    ModelInputSpec,
    ModelManifest,
    PreprocessorRequirement,
    VerifiedModelPackage,
    recheck_verified_package,
)
from tool_defect.plugin_api import (
    AlgorithmOutcome,
    AlgorithmOutput,
    PluginDescriptor,
    PluginError,
    PluginErrorCode,
    PreparedBatch,
    QualityStatus,
    RuntimeContext,
    TransformRecord,
    classify_unexpected,
    validate_algorithm_output,
)


_SENSITIVE_MARKERS = (
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "KEY",
    "AUTH",
    "COOKIE",
    "SESSION",
    "CERT",
    "CREDENTIAL",
    "DATABASE",
    "RABBIT",
    "S3_",
    "AWS_",
)
_ALLOWED_PLUGIN_MODULE_PREFIX = (
    "inference_service.plugins.algorithms.",
)


@dataclass(frozen=True)
class IsolationPolicy:
    allowed_environment: tuple[str, ...]
    temp_dir: Path
    memory_limit_mb: int = 1024
    cpu_time_seconds: int = 300
    network_enabled: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.allowed_environment, tuple)
            or any(
                not isinstance(name, str) or not name
                for name in self.allowed_environment
            )
            or len(set(self.allowed_environment))
            != len(self.allowed_environment)
        ):
            raise ValueError("隔离环境白名单必须是非重复字符串元组")
        if not isinstance(self.temp_dir, Path) or not self.temp_dir.is_absolute():
            raise ValueError("隔离工作目录必须是绝对路径")
        if (
            isinstance(self.memory_limit_mb, bool)
            or not isinstance(self.memory_limit_mb, int)
            or self.memory_limit_mb <= 0
            or isinstance(self.cpu_time_seconds, bool)
            or not isinstance(self.cpu_time_seconds, int)
            or self.cpu_time_seconds <= 0
        ):
            raise ValueError("隔离资源限制必须是正整数")
        if not isinstance(self.network_enabled, bool):
            raise TypeError("隔离网络开关必须是布尔值")

    def sanitized_environment(self) -> dict[str, str]:
        allowed = set(self.allowed_environment)
        return {
            key: value
            for key, value in os.environ.items()
            if key in allowed
            and not any(marker in key.upper() for marker in _SENSITIVE_MARKERS)
        }


@dataclass(frozen=True)
class WorkerPluginSpec:
    module: str
    class_name: str
    descriptor: PluginDescriptor
    init_kwargs: Mapping[str, Any]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.module, str)
            or not self.module.startswith(_ALLOWED_PLUGIN_MODULE_PREFIX)
            or not isinstance(self.class_name, str)
            or not self.class_name.isidentifier()
        ):
            raise ValueError("隔离插件导入路径不在允许列表")
        if not isinstance(self.descriptor, PluginDescriptor):
            raise TypeError("隔离插件必须携带严格描述符")
        if not isinstance(self.init_kwargs, Mapping):
            raise TypeError("隔离插件初始化参数必须是映射")
        try:
            json.dumps(
                self.init_kwargs,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise ValueError("隔离插件初始化参数必须是有限 JSON") from error
        object.__setattr__(
            self,
            "init_kwargs",
            MappingProxyType(dict(self.init_kwargs)),
        )

    @classmethod
    def from_plugin_class(
        cls,
        plugin_class: type,
        *,
        init_kwargs: Mapping[str, Any] | None = None,
    ) -> "WorkerPluginSpec":
        descriptor = getattr(plugin_class, "descriptor", None)
        return cls(
            module=plugin_class.__module__,
            class_name=plugin_class.__name__,
            descriptor=descriptor,
            init_kwargs=dict(init_kwargs or {}),
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "class_name": self.class_name,
            "plugin_id": self.descriptor.plugin_id,
            "plugin_version": self.descriptor.plugin_version,
            "init_kwargs": dict(self.init_kwargs),
        }


class ModelWorkerProcess:
    """实现算法插件协议的进程代理；加载、预热和预测均在子进程。"""

    def __init__(
        self,
        policy: IsolationPolicy,
        plugin_spec: WorkerPluginSpec,
        *,
        startup_timeout_seconds: float = 120.0,
    ):
        self._policy = policy
        self._plugin_spec = plugin_spec
        self._startup_timeout_seconds = float(startup_timeout_seconds)
        if self._startup_timeout_seconds <= 0:
            raise ValueError("隔离工作进程启动超时必须为正数")
        self._process: multiprocessing.Process | None = None
        self._parent = None
        self._loaded = False

    @property
    def descriptor(self) -> PluginDescriptor:
        return self._plugin_spec.descriptor

    @property
    def alive(self) -> bool:
        return bool(self._process is not None and self._process.is_alive())

    def load(
        self,
        package: VerifiedModelPackage,
        context: RuntimeContext,
    ) -> None:
        if self.alive or self._loaded:
            raise RuntimeError("隔离模型工作进程已经加载")
        self._policy.temp_dir.mkdir(parents=True, exist_ok=True)
        spawn_context = multiprocessing.get_context("spawn")
        parent, child = spawn_context.Pipe()
        self._parent = parent
        self._process = spawn_context.Process(
            target=_worker_main,
            args=(
                child,
                self._policy.sanitized_environment(),
                str(self._policy.temp_dir),
                self._policy.memory_limit_mb,
                self._policy.cpu_time_seconds,
                self._policy.network_enabled,
                self._plugin_spec.to_wire(),
                _package_to_wire(package),
                _context_to_wire(context),
            ),
            daemon=True,
        )
        self._process.start()
        child.close()
        if not parent.poll(self._startup_timeout_seconds):
            self._force_stop()
            raise PluginError.create(
                PluginErrorCode.RUNTIME_TRANSIENT,
                "model_load",
                "隔离模型工作进程启动超时",
            )
        try:
            response = parent.recv()
        except (EOFError, OSError) as error:
            self._force_stop()
            raise PluginError.create(
                PluginErrorCode.PLUGIN_BUG,
                "model_load",
                "隔离模型工作进程启动期间异常退出",
                {"exception_type": type(error).__name__},
            ) from error
        if response.get("status") != "READY":
            self._force_stop()
            raise _error_from_wire(
                response.get("error"),
                stage="model_load",
                message="隔离模型工作进程加载失败",
            )
        self._loaded = True

    def warmup(self) -> None:
        if not self._loaded or not self.alive:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "model_warmup",
                "隔离模型工作进程尚未预热",
            )
        health = self.health()
        if not health.get("ready", False):
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "model_warmup",
                "隔离模型工作进程预热后未就绪",
            )

    def predict(
        self,
        prepared: PreparedBatch,
        context: RuntimeContext,
    ) -> AlgorithmOutput:
        timeout = max(
            0.1,
            min(3600.0, context.deadline_monotonic - time.monotonic()),
        )
        response = self._request(
            {
                "command": "PREDICT",
                "prepared": _prepared_to_wire(prepared),
                "context": _context_to_wire(context),
            },
            timeout=timeout,
            stage="inference",
        )
        if response.get("status") != "OK":
            raise _error_from_wire(
                response.get("error"),
                stage="inference",
                message="隔离算法预测失败",
            )
        output = _output_from_wire(response["output"])
        validate_algorithm_output(output)
        return output

    def ping(self) -> dict[str, Any]:
        return self._request(
            {"command": "PING"},
            timeout=5.0,
            stage="runtime_slot",
        )

    def environment_keys(self) -> tuple[str, ...]:
        response = self._request(
            {"command": "ENVIRONMENT_KEYS"},
            timeout=5.0,
            stage="runtime_slot",
        )
        return tuple(response["keys"])

    def isolation_status(self) -> Mapping[str, Any]:
        response = self._request(
            {"command": "ISOLATION_STATUS"},
            timeout=5.0,
            stage="runtime_slot",
        )
        return MappingProxyType(dict(response["isolation"]))

    def health(self) -> Mapping[str, Any]:
        if not self._loaded or not self.alive:
            return {"ready": False, "isolated": True}
        response = self._request(
            {"command": "HEALTH"},
            timeout=5.0,
            stage="runtime_slot",
        )
        if response.get("status") != "OK":
            return {"ready": False, "isolated": True}
        health = dict(response["health"])
        health["isolated"] = True
        return health

    def close(self) -> None:
        if self.alive and self._parent is not None:
            try:
                self._parent.send({"command": "CLOSE"})
                if self._parent.poll(5):
                    self._parent.recv()
            except (BrokenPipeError, EOFError, OSError):
                pass
            self._process.join(timeout=5)
        if self._process is not None and self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=5)
        elif self._process is not None:
            self._process.join(timeout=5)
        if self._parent is not None:
            self._parent.close()
        self._process = None
        self._parent = None
        self._loaded = False

    def _request(
        self,
        request: Mapping[str, Any],
        *,
        timeout: float,
        stage: str,
    ) -> dict[str, Any]:
        if not self.alive or self._parent is None:
            raise PluginError.create(
                PluginErrorCode.PLUGIN_BUG,
                stage,
                "隔离模型工作进程异常退出",
            )
        try:
            self._parent.send(dict(request))
            if not self._parent.poll(timeout):
                # 超时请求仍可能在子进程中继续执行；必须销毁进程，
                # 否则迟到响应会被下一条健康检查误读，造成协议串线。
                self._force_stop()
                raise PluginError.create(
                    PluginErrorCode.RUNTIME_TRANSIENT,
                    stage,
                    "隔离模型工作进程响应超时",
                )
            response = self._parent.recv()
        except PluginError:
            raise
        except (BrokenPipeError, EOFError, OSError) as error:
            self._force_stop()
            raise PluginError.create(
                PluginErrorCode.PLUGIN_BUG,
                stage,
                "隔离模型工作进程通信失败",
                {"exception_type": type(error).__name__},
            ) from error
        if not isinstance(response, dict):
            raise PluginError.create(
                PluginErrorCode.PLUGIN_BUG,
                stage,
                "隔离模型工作进程响应协议非法",
            )
        return response

    def _force_stop(self) -> None:
        if self._process is not None:
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(timeout=5)
        if self._parent is not None:
            self._parent.close()
        self._process = None
        self._parent = None
        self._loaded = False


class _WorkerCancellation:
    def __init__(self, deadline_monotonic: float):
        self._deadline = float(deadline_monotonic)

    def is_cancelled(self) -> bool:
        return time.monotonic() >= self._deadline

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise PluginError.create(
                PluginErrorCode.RUNTIME_TRANSIENT,
                "inference",
                "隔离算法执行已经超时",
            )


def _worker_main(
    connection,
    environment: dict[str, str],
    temp_dir: str,
    memory_limit_mb: int,
    cpu_time_seconds: int,
    network_enabled: bool,
    plugin_spec: dict[str, Any],
    package_payload: dict[str, Any],
    context_payload: dict[str, Any],
) -> None:
    plugin = None
    try:
        os.environ.clear()
        os.environ.update(environment)
        os.chdir(temp_dir)
        _apply_resource_limits(memory_limit_mb, cpu_time_seconds)
        if not network_enabled:
            _disable_network()
        package = _package_from_wire(package_payload)
        recheck_verified_package(package)
        plugin = _instantiate_plugin(plugin_spec)
        context = _context_from_wire(context_payload, Path(temp_dir))
        plugin.load(package, context)
        plugin.warmup()
        health = _plain_mapping(plugin.health())
        if not bool(health.get("ready", False)):
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "model_warmup",
                "隔离插件预热后未报告就绪",
            )
        connection.send({"status": "READY", "health": health})
    except Exception as error:
        connection.send(
            {
                "status": "LOAD_FAILED",
                "error": _error_to_wire(error, "model_load"),
            }
        )
        if plugin is not None:
            try:
                plugin.close()
            except Exception:
                pass
        return

    try:
        while True:
            request = connection.recv()
            command = request.get("command")
            if command == "PING":
                connection.send({"status": "OK"})
            elif command == "ENVIRONMENT_KEYS":
                connection.send(
                    {"status": "OK", "keys": sorted(os.environ)}
                )
            elif command == "ISOLATION_STATUS":
                connection.send(
                    {
                        "status": "OK",
                        "isolation": {
                            "network_enabled": network_enabled,
                            "network_blocked": (
                                _network_creation_is_blocked()
                                if not network_enabled
                                else False
                            ),
                            "memory_limit_mb": memory_limit_mb,
                            "cpu_time_seconds": cpu_time_seconds,
                        },
                    }
                )
            elif command == "HEALTH":
                connection.send(
                    {
                        "status": "OK",
                        "health": _plain_mapping(plugin.health()),
                    }
                )
            elif command == "PREDICT":
                try:
                    prepared = _prepared_from_wire(request["prepared"])
                    context = _context_from_wire(
                        request["context"], Path(temp_dir)
                    )
                    output = plugin.predict(prepared, context)
                    validate_algorithm_output(output)
                    connection.send(
                        {
                            "status": "OK",
                            "output": _output_to_wire(output),
                        }
                    )
                except Exception as error:
                    connection.send(
                        {
                            "status": "ERROR",
                            "error": _error_to_wire(error, "inference"),
                        }
                    )
            elif command == "CLOSE":
                plugin.close()
                connection.send({"status": "CLOSED"})
                return
            else:
                connection.send(
                    {"status": "ERROR", "reason": "UNKNOWN_COMMAND"}
                )
    except (EOFError, BrokenPipeError, OSError):
        try:
            plugin.close()
        except Exception:
            pass


def _instantiate_plugin(payload: Mapping[str, Any]) -> Any:
    module_name = payload.get("module")
    class_name = payload.get("class_name")
    if (
        not isinstance(module_name, str)
        or not module_name.startswith(_ALLOWED_PLUGIN_MODULE_PREFIX)
        or not isinstance(class_name, str)
        or not class_name.isidentifier()
    ):
        raise PluginError.create(
            PluginErrorCode.MODEL_INCOMPATIBLE,
            "model_load",
            "隔离插件导入路径不在允许列表",
        )
    module = importlib.import_module(module_name)
    plugin_class = getattr(module, class_name)
    descriptor = getattr(plugin_class, "descriptor", None)
    if (
        not isinstance(descriptor, PluginDescriptor)
        or descriptor.plugin_id != payload.get("plugin_id")
        or descriptor.plugin_version != payload.get("plugin_version")
    ):
        raise PluginError.create(
            PluginErrorCode.MODEL_INCOMPATIBLE,
            "model_load",
            "隔离插件描述符与父进程不一致",
        )
    return plugin_class(**dict(payload.get("init_kwargs", {})))


def _package_to_wire(package: VerifiedModelPackage) -> dict[str, Any]:
    manifest = package.manifest
    return {
        "root": str(package.root),
        "package_sha256": package.package_sha256,
        "file_sha256": dict(package.file_sha256),
        "signer_key_id": package.signer_key_id,
        "verification_report": _plain_mapping(
            package.verification_report
        ),
        "manifest": {
            "model_name": manifest.model_name,
            "model_version": manifest.model_version,
            "framework": manifest.framework,
            "framework_version": manifest.framework_version,
            "keras_version": manifest.keras_version,
            "python_version": manifest.python_version,
            "input_spec": {
                "shape": list(manifest.input_spec.shape),
                "dtype": manifest.input_spec.dtype,
                "color_space": manifest.input_spec.color_space,
                "value_range": list(manifest.input_spec.value_range),
            },
            "output_names": list(manifest.output_names),
            "label_map": dict(manifest.label_map),
            "preprocessor": {
                "plugin_id": manifest.preprocessor.plugin_id,
                "plugin_version": manifest.preprocessor.plugin_version,
                "config_sha256": manifest.preprocessor.config_sha256,
            },
            "dataset_version": manifest.dataset_version,
            "source_run_id": manifest.source_run_id,
        },
    }


def _package_from_wire(payload: Mapping[str, Any]) -> VerifiedModelPackage:
    manifest_payload = payload["manifest"]
    input_payload = manifest_payload["input_spec"]
    preprocessor_payload = manifest_payload["preprocessor"]
    manifest = ModelManifest(
        model_name=manifest_payload["model_name"],
        model_version=manifest_payload["model_version"],
        framework=manifest_payload["framework"],
        framework_version=manifest_payload["framework_version"],
        keras_version=manifest_payload["keras_version"],
        python_version=manifest_payload["python_version"],
        input_spec=ModelInputSpec(
            shape=tuple(input_payload["shape"]),
            dtype=input_payload["dtype"],
            color_space=input_payload["color_space"],
            value_range=tuple(input_payload["value_range"]),
        ),
        output_names=tuple(manifest_payload["output_names"]),
        label_map=MappingProxyType(
            {
                int(index): label
                for index, label in manifest_payload["label_map"].items()
            }
        ),
        preprocessor=PreprocessorRequirement(
            plugin_id=preprocessor_payload["plugin_id"],
            plugin_version=preprocessor_payload["plugin_version"],
            config_sha256=preprocessor_payload["config_sha256"],
        ),
        dataset_version=manifest_payload["dataset_version"],
        source_run_id=manifest_payload["source_run_id"],
    )
    return VerifiedModelPackage(
        root=Path(payload["root"]).resolve(strict=True),
        manifest=manifest,
        package_sha256=payload["package_sha256"],
        file_sha256=MappingProxyType(dict(payload["file_sha256"])),
        signer_key_id=payload["signer_key_id"],
        verification_report=MappingProxyType(
            dict(payload["verification_report"])
        ),
    )


def _context_to_wire(context: RuntimeContext) -> dict[str, Any]:
    return {
        "run_id": context.run_id,
        "attempt_id": context.attempt_id,
        "pipeline_version": context.pipeline_version,
        "config_sha256": context.config_sha256,
        "code_signature": context.code_signature,
        "runtime_slot_id": context.runtime_slot_id,
        "device": context.device,
        "random_seed": context.random_seed,
        "deadline_monotonic": context.deadline_monotonic,
    }


def _context_from_wire(
    payload: Mapping[str, Any],
    temp_dir: Path,
) -> RuntimeContext:
    deadline = float(payload["deadline_monotonic"])
    return RuntimeContext(
        run_id=payload["run_id"],
        attempt_id=payload["attempt_id"],
        pipeline_version=payload["pipeline_version"],
        config_sha256=payload["config_sha256"],
        code_signature=payload["code_signature"],
        runtime_slot_id=payload["runtime_slot_id"],
        device=payload["device"],
        temp_dir=temp_dir.resolve(),
        random_seed=int(payload["random_seed"]),
        deadline_monotonic=deadline,
        cancellation=_WorkerCancellation(deadline),
    )


def _prepared_to_wire(prepared: PreparedBatch) -> dict[str, Any]:
    return {
        "tensors": {
            name: np.asarray(value) for name, value in prepared.tensors.items()
        },
        "coordinate_spaces": _plain_mapping(
            prepared.coordinate_spaces
        ),
        "transforms": [
            transform.to_mapping() for transform in prepared.transforms
        ],
        "artifacts": {
            name: np.asarray(value)
            for name, value in prepared.artifacts.items()
        },
        "quality_status": prepared.quality_status.value,
        "warnings": list(prepared.warnings),
        "metadata": _plain_mapping(prepared.metadata),
    }


def _prepared_from_wire(payload: Mapping[str, Any]) -> PreparedBatch:
    return PreparedBatch(
        tensors=dict(payload["tensors"]),
        coordinate_spaces=dict(payload["coordinate_spaces"]),
        transforms=tuple(
            TransformRecord(**item) for item in payload["transforms"]
        ),
        artifacts=dict(payload["artifacts"]),
        quality_status=QualityStatus(payload["quality_status"]),
        warnings=tuple(payload["warnings"]),
        metadata=dict(payload["metadata"]),
    )


def _output_to_wire(output: AlgorithmOutput) -> dict[str, Any]:
    return {
        "outcome": output.outcome.value,
        "class_probabilities": dict(output.class_probabilities),
        "masks": {
            name: np.asarray(value) for name, value in output.masks.items()
        },
        "regions": [
            _plain_mapping(region) for region in output.regions
        ],
        "scores": dict(output.scores),
        "warnings": list(output.warnings),
        "metadata": _plain_mapping(output.metadata),
    }


def _output_from_wire(payload: Mapping[str, Any]) -> AlgorithmOutput:
    return AlgorithmOutput(
        outcome=AlgorithmOutcome(payload["outcome"]),
        class_probabilities=dict(payload["class_probabilities"]),
        masks=dict(payload["masks"]),
        regions=tuple(payload["regions"]),
        scores=dict(payload["scores"]),
        warnings=tuple(payload["warnings"]),
        metadata=dict(payload["metadata"]),
    )


def _plain_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _plain_mapping(nested)
            for key, nested in value.items()
        }
    if isinstance(value, tuple):
        return [_plain_mapping(nested) for nested in value]
    if isinstance(value, list):
        return [_plain_mapping(nested) for nested in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _error_to_wire(error: Exception, stage: str) -> dict[str, Any]:
    classified = classify_unexpected(error, stage)
    return classified.info.to_mapping()


def _error_from_wire(
    payload: Any,
    *,
    stage: str,
    message: str,
) -> PluginError:
    if isinstance(payload, Mapping):
        try:
            code = PluginErrorCode(payload["code"])
            safe_message = str(payload["message"])
            details = payload.get("details", {})
            if not isinstance(details, Mapping):
                details = {}
            return PluginError.create(
                code,
                str(payload.get("stage", stage)),
                safe_message,
                dict(details),
            )
        except (KeyError, ValueError, TypeError):
            pass
    return PluginError.create(
        PluginErrorCode.PLUGIN_BUG,
        stage,
        message,
    )


def _apply_resource_limits(
    memory_limit_mb: int,
    cpu_time_seconds: int,
) -> None:
    try:
        import resource

        memory_bytes = int(memory_limit_mb) * 1024 * 1024
        resource.setrlimit(
            resource.RLIMIT_AS,
            (memory_bytes, memory_bytes),
        )
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (int(cpu_time_seconds), int(cpu_time_seconds)),
        )
    except (ImportError, OSError, ValueError):
        # Windows 等平台由外层容器或作业对象落实同一策略。
        return


def _disable_network() -> None:
    import socket

    def denied(*args, **kwargs):
        raise PermissionError("隔离模型工作进程禁止网络访问")

    socket.socket = denied
    socket.create_connection = denied


def _network_creation_is_blocked() -> bool:
    import socket

    try:
        candidate = socket.socket()
    except PermissionError:
        return True
    candidate.close()
    return False
