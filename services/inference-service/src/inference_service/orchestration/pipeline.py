"""对象物化、插件编排和后端接受语义。"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Mapping, Protocol

from tool_defect.inference.result_normalization import (
    DerivedArtifact,
    normalize_result,
)
from tool_defect.plugin_api import (
    FrameBundle,
    PluginError,
    PluginErrorCode,
    PluginDescriptor,
    QualityStatus,
    RuntimeContext,
    classify_unexpected,
    inconclusive_output,
)

_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_TRACEPARENT = re.compile(
    r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
)

from inference_service.clients.business_api import BusinessApiClient
from inference_service.model_runtime.slot import RuntimeSlot
from inference_service.orchestration.decoder import ImageDecoder
from inference_service.storage.materializer import (
    ObjectMaterializer,
    ObjectReference,
)


@dataclass(frozen=True)
class InferenceTask:
    message_id: str
    occurred_at: str
    traceparent: str
    detection_task_id: str
    capture_id: str
    pipeline_id: str
    recipe_id: str
    pipeline_version: str
    pipeline_config_sha256: str
    preprocessor_version: str
    algorithm_version: str
    model_version: str
    model_sha256: str
    images: tuple[ObjectReference, ...]
    deadline_monotonic: float

    def __post_init__(self) -> None:
        identifiers = (
            "message_id",
            "detection_task_id",
            "capture_id",
            "pipeline_id",
            "recipe_id",
        )
        versions = (
            "pipeline_version",
            "preprocessor_version",
            "algorithm_version",
            "model_version",
        )
        if any(
            not isinstance(getattr(self, name), str)
            or _UUID.fullmatch(getattr(self, name)) is None
            for name in identifiers
        ):
            raise ValueError("推理任务标识必须符合冻结 UUID 契约")
        if any(
            not isinstance(getattr(self, name), str)
            or _VERSION.fullmatch(getattr(self, name)) is None
            for name in versions
        ):
            raise ValueError("推理任务版本字段不符合冻结契约")
        if (
            not isinstance(self.traceparent, str)
            or _TRACEPARENT.fullmatch(self.traceparent) is None
        ):
            raise ValueError("推理任务 traceparent 格式非法")
        _parse_utc_timestamp(self.occurred_at, "occurred_at")
        if (
            _SHA256.fullmatch(self.pipeline_config_sha256) is None
            or _SHA256.fullmatch(self.model_sha256) is None
        ):
            raise ValueError("推理任务配置或模型 SHA-256 格式非法")
        if (
            not isinstance(self.images, tuple)
            or not self.images
            or any(
                not isinstance(image, ObjectReference)
                for image in self.images
            )
        ):
            raise TypeError("推理任务必须包含不可变对象引用元组")
        if not math.isfinite(self.deadline_monotonic):
            raise ValueError("推理任务截止时间必须是有限值")

    @classmethod
    def from_contract(
        cls,
        payload: Mapping[str, Any],
        *,
        recipe_id: str,
        model_sha256: str,
        now_utc: datetime | None = None,
        now_monotonic: float | None = None,
    ) -> "InferenceTask":
        """从冻结事件契约构造内部任务，并显式注入登记信息。"""

        if not isinstance(payload, Mapping):
            raise TypeError("推理事件必须是对象")
        fields = {
            "event_type",
            "message_id",
            "occurred_at",
            "traceparent",
            "detection_task_id",
            "capture_id",
            "pipeline",
            "images",
            "deadline_at",
        }
        if set(payload) != fields or payload.get("event_type") != (
            "tool_defect.inference.task.v1"
        ):
            raise ValueError("推理事件字段或事件类型与冻结契约不一致")
        pipeline = payload["pipeline"]
        pipeline_fields = {
            "pipeline_id",
            "version",
            "config_sha256",
            "preprocessor_version",
            "algorithm_version",
            "model_version",
        }
        if not isinstance(pipeline, Mapping) or set(pipeline) != pipeline_fields:
            raise ValueError("推理事件流水线字段与冻结契约不一致")
        images_payload = payload["images"]
        if (
            not isinstance(images_payload, list)
            or not 1 <= len(images_payload) <= 16
        ):
            raise ValueError("推理事件图片数量与冻结契约不一致")
        deadline_at = _parse_utc_timestamp(
            payload["deadline_at"], "deadline_at"
        )
        current_utc = now_utc or datetime.now(timezone.utc)
        if current_utc.tzinfo is None:
            raise ValueError("当前时间必须包含时区")
        current_monotonic = (
            time.monotonic()
            if now_monotonic is None
            else float(now_monotonic)
        )
        deadline_monotonic = current_monotonic + (
            deadline_at - current_utc.astimezone(timezone.utc)
        ).total_seconds()
        return cls(
            message_id=payload["message_id"],
            occurred_at=payload["occurred_at"],
            traceparent=payload["traceparent"],
            detection_task_id=payload["detection_task_id"],
            capture_id=payload["capture_id"],
            pipeline_id=pipeline["pipeline_id"],
            recipe_id=recipe_id,
            pipeline_version=pipeline["version"],
            pipeline_config_sha256=pipeline["config_sha256"],
            preprocessor_version=pipeline["preprocessor_version"],
            algorithm_version=pipeline["algorithm_version"],
            model_version=pipeline["model_version"],
            model_sha256=model_sha256,
            images=tuple(
                ObjectReference.from_contract(image)
                for image in images_payload
            ),
            deadline_monotonic=deadline_monotonic,
        )


@dataclass(frozen=True)
class ExecutionAcceptance:
    accepted: bool
    attempt_id: str
    result_sha256: str
    failure: bool

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool) or not isinstance(
            self.failure, bool
        ):
            raise TypeError("回调接受和失败标记必须是布尔值")
        if not self.attempt_id or _SHA256.fullmatch(
            self.result_sha256
        ) is None:
            raise ValueError("执行接受对象标识或结果哈希非法")


class ArtifactPublisher(Protocol):
    async def publish(
        self,
        attempt_id: str,
        name: str,
        artifact: DerivedArtifact,
    ) -> Mapping[str, Any]:
        ...


class InferenceOrchestrator:
    def __init__(
        self,
        *,
        materializer: ObjectMaterializer,
        decoder: ImageDecoder,
        preprocessor: Any,
        runtime_slot: RuntimeSlot,
        callback: BusinessApiClient,
        artifact_publisher: ArtifactPublisher,
        runtime_id: str,
        runtime_version: str,
        temp_root: Path,
    ):
        self._materializer = materializer
        self._decoder = decoder
        self._preprocessor = preprocessor
        self._runtime_slot = runtime_slot
        self._callback = callback
        self._artifact_publisher = artifact_publisher
        self._runtime_id = runtime_id
        self._runtime_version = runtime_version
        if (
            not isinstance(self._runtime_id, str)
            or not self._runtime_id
            or len(self._runtime_id) > 128
            or not isinstance(self._runtime_version, str)
            or _VERSION.fullmatch(self._runtime_version) is None
        ):
            raise ValueError("推理运行时标识或版本格式非法")
        self._temp_root = Path(temp_root)
        self._temp_root.mkdir(parents=True, exist_ok=True)
        self._temp_root = self._temp_root.resolve(strict=True)
        self._preprocessor_lock = asyncio.Lock()

    async def execute(self, task: InferenceTask) -> ExecutionAcceptance:
        attempt_id = await self._callback.create_attempt(
            task.detection_task_id,
            task.message_id,
            self._runtime_id,
            self._runtime_version,
            task.model_sha256,
            task.traceparent,
        )
        try:
            if time.monotonic() >= task.deadline_monotonic:
                raise PluginError.create(
                    PluginErrorCode.RUNTIME_TRANSIENT,
                    "orchestration",
                    "推理任务在执行前已经超过截止时间",
                )
            expected_identity = (
                task.model_version,
                task.model_sha256.removeprefix("sha256:"),
            )
            if self._runtime_slot.model_identity != expected_identity:
                raise PluginError.create(
                    PluginErrorCode.MODEL_INCOMPATIBLE,
                    "runtime_slot",
                    "任务模型版本与运行槽不一致",
                )
            (
                preprocessor_descriptor,
                algorithm_descriptor,
            ) = self._verify_plugin_bindings(task)
            with tempfile.TemporaryDirectory(
                prefix="attempt-" + _safe_local_token(attempt_id) + "-",
                dir=self._temp_root,
            ) as temp_name:
                temp_dir = Path(temp_name)
                started = time.perf_counter()
                materialized = [
                    await self._materializer.materialize(reference, temp_dir)
                    for reference in task.images
                ]
                download_ms = _elapsed_ms(started)
                started = time.perf_counter()
                frames = tuple(
                    self._decoder.decode(item) for item in materialized
                )
                decode_ms = _elapsed_ms(started)
                context = RuntimeContext(
                    run_id=task.message_id,
                    attempt_id=attempt_id,
                    pipeline_version=task.pipeline_version,
                    config_sha256=task.pipeline_config_sha256,
                    code_signature="runtime:" + self._runtime_id,
                    runtime_slot_id=self._runtime_slot.slot_id,
                    device=self._runtime_slot.profile.device,
                    temp_dir=temp_dir.resolve(),
                    random_seed=0,
                    deadline_monotonic=task.deadline_monotonic,
                    cancellation=_DeadlineCancellation(
                        task.deadline_monotonic
                    ),
                )
                bundle = FrameBundle(
                    capture_id=task.capture_id,
                    frames=frames,
                    recipe_id=task.recipe_id,
                )
                started = time.perf_counter()
                prepared = await self._prepare(bundle, context)
                preprocess_ms = _elapsed_ms(started)
                started = time.perf_counter()
                if prepared.quality_status == QualityStatus.REJECTED:
                    algorithm_output = inconclusive_output(
                        "PREPROCESS_REJECTED"
                    )
                else:
                    algorithm_output = await self._runtime_slot.execute(
                        prepared, context
                    )
                inference_ms = _elapsed_ms(started)
                started = time.perf_counter()
                normalized = normalize_result(prepared, algorithm_output)
                postprocess_ms = _elapsed_ms(started)
                published = []
                started = time.perf_counter()
                for name, artifact in normalized.artifacts.items():
                    reference = await self._artifact_publisher.publish(
                        attempt_id, name, artifact
                    )
                    published.append(
                        _validated_published_artifact(
                            artifact, reference
                        )
                    )
                upload_ms = _elapsed_ms(started)
                payload = dict(normalized.payload)
                payload.update(
                    {
                        "schema_version": "1.0",
                        "capture_id": task.capture_id,
                        "detection_task_id": task.detection_task_id,
                        "attempt_id": attempt_id,
                        "execution_status": "SUCCEEDED",
                        "preprocess": {
                            "plugin_id": (
                                preprocessor_descriptor.plugin_id
                            ),
                            "plugin_version": (
                                preprocessor_descriptor.plugin_version
                            ),
                            "config_sha256": (
                                self._preprocessor
                                .configuration_sha256.removeprefix(
                                    "sha256:"
                                )
                            ),
                            "quality_status": (
                                prepared.quality_status.value
                            ),
                            "warnings": list(prepared.warnings),
                        },
                        "algorithm": {
                            "plugin_id": algorithm_descriptor.plugin_id,
                            "plugin_version": (
                                algorithm_descriptor.plugin_version
                            ),
                            "model_version": task.model_version,
                            "model_sha256": (
                                task.model_sha256.removeprefix("sha256:")
                            ),
                        },
                        "timings_ms": {
                            "download": download_ms,
                            "decode": decode_ms,
                            "preprocess": preprocess_ms,
                            "inference": inference_ms,
                            "postprocess": postprocess_ms,
                            "upload": upload_ms,
                        },
                        "artifacts": published,
                    }
                )
                payload.pop("artifacts_pending", None)
                result_sha256 = _payload_sha256(payload)
                try:
                    acceptance = await self._callback.put_result(
                        attempt_id,
                        payload,
                        result_sha256,
                        task.traceparent,
                    )
                except Exception:
                    # 结果已确定但回调状态未知时保留同一结果哈希重试，
                    # 不能另行提交失败事实覆盖可能已接受的成功结果。
                    return ExecutionAcceptance(
                        accepted=False,
                        attempt_id=attempt_id,
                        result_sha256=result_sha256,
                        failure=False,
                    )
                return ExecutionAcceptance(
                    accepted=acceptance.accepted,
                    attempt_id=attempt_id,
                    result_sha256=result_sha256,
                    failure=False,
                )
        except Exception as error:
            plugin_error = classify_unexpected(error, "orchestration")
            acceptance = await self._callback.put_failure(
                attempt_id,
                plugin_error.info,
                task.traceparent,
            )
            return ExecutionAcceptance(
                accepted=acceptance.accepted,
                attempt_id=attempt_id,
                result_sha256=acceptance.result_sha256,
                failure=True,
            )

    async def _prepare(
        self,
        bundle: FrameBundle,
        context: RuntimeContext,
    ):
        if self._preprocessor.descriptor.thread_safe:
            return await asyncio.to_thread(
                self._preprocessor.prepare, bundle, context
            )
        async with self._preprocessor_lock:
            return await asyncio.to_thread(
                self._preprocessor.prepare, bundle, context
            )

    def _verify_plugin_bindings(
        self,
        task: InferenceTask,
    ) -> tuple[PluginDescriptor, PluginDescriptor]:
        preprocessor_descriptor = getattr(
            self._preprocessor, "descriptor", None
        )
        algorithm_descriptor = self._runtime_slot.algorithm_descriptor
        manifest = self._runtime_slot.model_manifest
        if (
            not isinstance(preprocessor_descriptor, PluginDescriptor)
            or not isinstance(algorithm_descriptor, PluginDescriptor)
            or manifest is None
        ):
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "orchestration",
                "运行流水线缺少严格插件或模型描述符",
            )
        requirement = manifest.preprocessor
        actual = (
            preprocessor_descriptor.plugin_id,
            preprocessor_descriptor.plugin_version,
            getattr(
                self._preprocessor, "configuration_sha256", None
            ),
        )
        expected = (
            requirement.plugin_id,
            requirement.plugin_version,
            requirement.config_sha256,
        )
        if actual != expected:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "orchestration",
                "预处理插件与可信模型包绑定不一致",
                {
                    "expected": list(expected),
                    "actual": list(actual),
                },
            )
        event_versions = (
            task.preprocessor_version,
            task.algorithm_version,
        )
        loaded_versions = (
            f"{preprocessor_descriptor.plugin_id}/"
            f"{preprocessor_descriptor.plugin_version}",
            f"{algorithm_descriptor.plugin_id}/"
            f"{algorithm_descriptor.plugin_version}",
        )
        if event_versions != loaded_versions:
            raise PluginError.create(
                PluginErrorCode.MODEL_INCOMPATIBLE,
                "orchestration",
                "任务插件版本与已加载流水线不一致",
                {
                    "expected": list(event_versions),
                    "actual": list(loaded_versions),
                },
            )
        return preprocessor_descriptor, algorithm_descriptor


class _DeadlineCancellation:
    def __init__(self, deadline_monotonic: float):
        self._deadline = deadline_monotonic

    def is_cancelled(self) -> bool:
        return time.monotonic() >= self._deadline

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise PluginError.create(
                PluginErrorCode.RUNTIME_TRANSIENT,
                "orchestration",
                "推理任务已经取消或超时",
            )


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_local_token(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 6)


def _validated_published_artifact(
    artifact: DerivedArtifact,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "kind",
        "image_id",
        "object",
    }:
        raise PluginError.create(
            PluginErrorCode.PLUGIN_BUG,
            "upload",
            "派生对象发布器返回字段与冻结契约不一致",
        )
    object_reference = value["object"]
    required = {
        "bucket",
        "object_key",
        "sha256",
        "size_bytes",
        "media_type",
    }
    allowed = required.union({"object_version"})
    if (
        value["kind"] != artifact.kind
        or not isinstance(value["image_id"], str)
        or not value["image_id"]
        or not isinstance(object_reference, Mapping)
        or not required.issubset(object_reference)
        or set(object_reference).difference(allowed)
    ):
        raise PluginError.create(
            PluginErrorCode.PLUGIN_BUG,
            "upload",
            "派生对象发布器返回非法对象引用",
        )
    sha256 = object_reference["sha256"]
    if (
        not isinstance(sha256, str)
        or _SHA256.fullmatch(sha256) is None
    ):
        raise PluginError.create(
            PluginErrorCode.PLUGIN_BUG,
            "upload",
            "派生对象发布器返回非法 SHA-256",
        )
    result = {
        "kind": artifact.kind,
        "image_id": value["image_id"],
        "object": dict(object_reference),
    }
    result["object"]["sha256"] = sha256.removeprefix("sha256:")
    return result


def _parse_utc_timestamp(value: Any, field: str) -> datetime:
    if (
        not isinstance(value, str)
        or not value.endswith("Z")
        or len(value) > 64
    ):
        raise ValueError(f"推理任务 {field} 必须是 UTC 时间")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"推理任务 {field} 格式非法") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(
        parsed
    ):
        raise ValueError(f"推理任务 {field} 必须是 UTC 时间")
    return parsed
