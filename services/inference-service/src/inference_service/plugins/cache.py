"""原子、可校验且可自动重建的预处理缓存。"""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping
from uuid import uuid4
import zipfile

import numpy as np

from tool_defect.plugin_api import (
    FrameBundle,
    PluginDescriptor,
    PreparedBatch,
    QualityStatus,
    RuntimeContext,
    TransformRecord,
    config_sha256,
)


_SHA256 = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
_CACHE_KEY = re.compile(r"^[0-9a-f]{64}$")
_CACHE_FORMAT_VERSION = 1


class CacheEntryState(str, Enum):
    STAGING = "STAGING"
    AVAILABLE = "AVAILABLE"
    INVALID = "INVALID"


@dataclass(frozen=True)
class CacheLookup:
    state: CacheEntryState
    value: PreparedBatch | None
    reason: str | None = None


def preprocessing_cache_key(
    source_sha256: str,
    descriptor: PluginDescriptor,
    configuration_sha256: str,
    code_signature: str,
) -> str:
    source_match = _SHA256.fullmatch(source_sha256)
    config_match = _SHA256.fullmatch(configuration_sha256)
    if source_match is None or config_match is None:
        raise ValueError("缓存键要求合法的源文件和配置 SHA-256")
    if not code_signature:
        raise ValueError("缓存键要求非空代码签名")
    digest = hashlib.sha256()
    for value in (
        source_match.group(1),
        descriptor.plugin_id,
        descriptor.plugin_version,
        config_match.group(1),
        code_signature,
    ):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return digest.hexdigest()


class PreparedBatchCache:
    def __init__(
        self,
        root: Path,
        *,
        maximum_archive_bytes: int = 256 * 1024 * 1024,
        maximum_uncompressed_bytes: int = 1024 * 1024 * 1024,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._maximum_archive_bytes = int(maximum_archive_bytes)
        self._maximum_uncompressed_bytes = int(
            maximum_uncompressed_bytes
        )
        if (
            self._maximum_archive_bytes <= 0
            or self._maximum_uncompressed_bytes <= 0
        ):
            raise ValueError("缓存大小限制必须为正数")

    def load(self, key: str) -> CacheLookup:
        path = self._available_path(key)
        if not path.exists():
            return CacheLookup(CacheEntryState.INVALID, None, "CACHE_MISS")
        try:
            value = self._decode(path, key)
        except Exception as error:
            self._mark_invalid(path, key)
            return CacheLookup(
                CacheEntryState.INVALID,
                None,
                type(error).__name__,
            )
        return CacheLookup(CacheEntryState.AVAILABLE, value)

    def store(self, key: str, value: PreparedBatch) -> None:
        self._validate_key(key)
        staging = self.root / f".{key}.{uuid4().hex}.staging.npz"
        arrays, manifest = _encode_batch(key, value)
        arrays["__manifest__"] = np.frombuffer(
            _canonical_json(manifest), dtype=np.uint8
        )
        try:
            with staging.open("xb") as handle:
                np.savez_compressed(handle, **arrays)
                handle.flush()
                os.fsync(handle.fileno())
            if staging.stat().st_size > self._maximum_archive_bytes:
                raise ValueError("预处理缓存归档超过大小限制")
            os.replace(staging, self._available_path(key))
        finally:
            if staging.exists():
                staging.unlink()

    def get_or_create(
        self,
        key: str,
        builder: Callable[[], PreparedBatch],
    ) -> tuple[PreparedBatch, bool]:
        lookup = self.load(key)
        if lookup.state == CacheEntryState.AVAILABLE:
            assert lookup.value is not None
            return lookup.value, True
        value = builder()
        if not isinstance(value, PreparedBatch):
            raise TypeError("缓存构建器必须返回 PreparedBatch")
        self.store(key, value)
        return value, False

    def cleanup_orphans(self, *, older_than_seconds: float) -> int:
        cutoff = time.time() - float(older_than_seconds)
        removed = 0
        for path in self.root.glob(".*.staging.npz"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        return removed

    def _decode(self, path: Path, key: str) -> PreparedBatch:
        if path.is_symlink() or not path.is_file():
            raise ValueError("缓存对象不是普通文件")
        if path.stat().st_size > self._maximum_archive_bytes:
            raise ValueError("缓存归档超过大小限制")
        with zipfile.ZipFile(path) as archive:
            total = sum(item.file_size for item in archive.infolist())
            if total > self._maximum_uncompressed_bytes:
                raise ValueError("缓存展开大小超过限制")
        with np.load(path, allow_pickle=False) as archive:
            if "__manifest__" not in archive.files:
                raise ValueError("缓存缺少清单")
            manifest_bytes = np.asarray(
                archive["__manifest__"], dtype=np.uint8
            ).tobytes()
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if (
                not isinstance(manifest, dict)
                or manifest.get("cache_format_version")
                != _CACHE_FORMAT_VERSION
                or manifest.get("state") != CacheEntryState.AVAILABLE.value
                or manifest.get("cache_key") != key
            ):
                raise ValueError("缓存清单身份或状态非法")
            tensors = _decode_arrays(
                archive, manifest.get("tensors"), "tensor"
            )
            artifacts = _decode_arrays(
                archive, manifest.get("artifacts"), "artifact"
            )
        transforms_payload = manifest.get("transforms")
        if not isinstance(transforms_payload, list):
            raise ValueError("缓存几何变换链非法")
        transforms = tuple(
            _decode_transform(item) for item in transforms_payload
        )
        coordinate_spaces = manifest.get("coordinate_spaces")
        metadata = manifest.get("metadata")
        warnings = manifest.get("warnings")
        if (
            not isinstance(coordinate_spaces, dict)
            or not isinstance(metadata, dict)
            or not isinstance(warnings, list)
            or any(not isinstance(item, str) for item in warnings)
        ):
            raise ValueError("缓存批次元数据非法")
        try:
            quality = QualityStatus(manifest["quality_status"])
        except (KeyError, ValueError) as error:
            raise ValueError("缓存质量状态非法") from error
        return PreparedBatch(
            tensors=tensors,
            coordinate_spaces=coordinate_spaces,
            transforms=transforms,
            artifacts=artifacts,
            quality_status=quality,
            warnings=tuple(warnings),
            metadata=metadata,
        )

    def _mark_invalid(self, path: Path, key: str) -> None:
        invalid = self.root / f"{key}.invalid.npz"
        try:
            os.replace(path, invalid)
        except OSError:
            return

    def _available_path(self, key: str) -> Path:
        self._validate_key(key)
        return self.root / f"{key}.available.npz"

    @staticmethod
    def _validate_key(key: str) -> None:
        if _CACHE_KEY.fullmatch(key) is None:
            raise ValueError("缓存键必须是 64 位小写十六进制字符串")


class CachedPreprocessor:
    """在不改变具体预处理器逻辑的前提下增加内容寻址缓存。"""

    def __init__(
        self,
        plugin: Any,
        configuration: Mapping[str, Any],
        cache: PreparedBatchCache,
    ):
        descriptor = getattr(plugin, "descriptor", None)
        if not isinstance(descriptor, PluginDescriptor):
            raise TypeError("被包装预处理器缺少合法描述符")
        self.descriptor = descriptor
        self._plugin = plugin
        self._configuration_sha256 = config_sha256(configuration)
        self._cache = cache
        self.last_cache_hit = False

    @property
    def configuration_sha256(self) -> str:
        return self._configuration_sha256

    def validate_config(self, configuration: Mapping[str, Any]) -> None:
        self._plugin.validate_config(configuration)

    def prepare(
        self,
        frames: FrameBundle,
        context: RuntimeContext,
    ) -> PreparedBatch:
        source_sha256 = _bundle_source_sha256(frames)
        key = preprocessing_cache_key(
            source_sha256,
            self.descriptor,
            self._configuration_sha256,
            context.code_signature,
        )
        result, hit = self._cache.get_or_create(
            key,
            lambda: self._plugin.prepare(frames, context),
        )
        self.last_cache_hit = hit
        return result

    def health(self) -> Mapping[str, Any]:
        health = dict(self._plugin.health())
        health["cache_last_hit"] = self.last_cache_hit
        return health

    def close(self) -> None:
        self._plugin.close()


def _bundle_source_sha256(frames: FrameBundle) -> str:
    if len(frames.frames) == 1:
        return frames.frames[0].sha256
    digest = hashlib.sha256()
    for frame in frames.frames:
        value = frame.sha256.removeprefix("sha256:").encode("ascii")
        digest.update(len(value).to_bytes(4, "big"))
        digest.update(value)
    return digest.hexdigest()


def _encode_batch(
    key: str,
    batch: PreparedBatch,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    arrays: dict[str, np.ndarray] = {}
    tensors = _encode_arrays(arrays, batch.tensors, "tensor")
    artifacts = _encode_arrays(arrays, batch.artifacts, "artifact")
    manifest = {
        "cache_format_version": _CACHE_FORMAT_VERSION,
        "state": CacheEntryState.AVAILABLE.value,
        "cache_key": key,
        "tensors": tensors,
        "artifacts": artifacts,
        "coordinate_spaces": _json_value(batch.coordinate_spaces),
        "transforms": [
            _json_value(transform.to_mapping())
            for transform in batch.transforms
        ],
        "quality_status": batch.quality_status.value,
        "warnings": list(batch.warnings),
        "metadata": _json_value(batch.metadata),
    }
    return arrays, manifest


def _encode_arrays(
    destination: dict[str, np.ndarray],
    source: Mapping[str, np.ndarray],
    prefix: str,
) -> list[dict[str, Any]]:
    manifest = []
    for index, name in enumerate(sorted(source)):
        array = np.ascontiguousarray(source[name])
        archive_key = f"{prefix}_{index}"
        destination[archive_key] = array
        manifest.append(
            {
                "name": name,
                "archive_key": archive_key,
                "shape": list(array.shape),
                "dtype": str(array.dtype),
                "content_sha256": _array_sha256(array),
            }
        )
    return manifest


def _decode_arrays(
    archive: Any,
    payload: Any,
    prefix: str,
) -> dict[str, np.ndarray]:
    if not isinstance(payload, list):
        raise ValueError("缓存数组清单非法")
    result: dict[str, np.ndarray] = {}
    for index, item in enumerate(payload):
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "name",
                "archive_key",
                "shape",
                "dtype",
                "content_sha256",
            }
            or item["archive_key"] != f"{prefix}_{index}"
            or not isinstance(item["name"], str)
            or item["name"] in result
        ):
            raise ValueError("缓存数组条目非法")
        array = np.ascontiguousarray(archive[item["archive_key"]])
        if (
            list(array.shape) != item["shape"]
            or str(array.dtype) != item["dtype"]
            or _array_sha256(array) != item["content_sha256"]
        ):
            raise ValueError("缓存数组内容哈希或形状不匹配")
        result[item["name"]] = array
    return result


def _decode_transform(payload: Any) -> TransformRecord:
    required = {
        "transform_type",
        "source_space",
        "target_space",
        "parameters",
        "artifact_refs",
        "invertible",
        "inverse_error_pixels",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("缓存几何变换记录非法")
    return TransformRecord(**payload)


def _array_sha256(array: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(
        json.dumps(list(array.shape), separators=(",", ":")).encode("ascii")
    )
    digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(nested)
            for key, nested in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(nested) for nested in value]
    if isinstance(value, np.generic):
        return value.item()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"缓存元数据包含不可序列化类型：{type(value).__name__}")
