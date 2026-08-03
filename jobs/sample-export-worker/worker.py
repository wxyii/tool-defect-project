#!/usr/bin/env python3
"""R7 样本导出 worker 核心。

worker 只接收候选来源快照和对象读取/写入边界，不访问业务数据库中的训练或数据集表。
每个候选独立校验对象 SHA-256、大小、媒体类型和版本证据；单项失败进入清单，不能
把部分成功标记为完整成功。压缩包、清单和记录均以确定性字节生成，便于重复核对。
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
ALLOWED_IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg"}
RESULT_MEDIA_TYPE = "application/json"
PACKAGE_MEDIA_TYPE = "application/zip"
TRACEPARENT_PATTERN = re.compile(
    r"^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$"
)


class ExportFailure(RuntimeError):
    """永久的候选数据或对象完整性失败。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RetryableExportFailure(RuntimeError):
    """对象存储或消息依赖暂时不可用；不能把该次运行标为成功。"""


class ObjectReader(Protocol):
    def read(self, reference: Mapping[str, Any]) -> bytes: ...


class ObjectWriter(Protocol):
    def put(self, bucket: str, object_key: str, media_type: str, data: bytes) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class CandidateInput:
    candidate_id: str
    source_snapshot: Mapping[str, Any]


@dataclass(frozen=True)
class ItemResult:
    candidate_id: str
    status: str
    files: tuple[Mapping[str, Any], ...] = ()
    error_code: str | None = None
    error_detail_digest: str | None = None


@dataclass(frozen=True)
class ExportBuildResult:
    status: str
    package_bytes: bytes
    manifest_bytes: bytes
    exported_count: int
    failed_count: int
    exported_candidate_ids: tuple[str, ...]
    failed_candidate_ids: tuple[str, ...]
    items: tuple[ItemResult, ...]


@dataclass(frozen=True)
class PublishedExport:
    status: str
    package: Mapping[str, Any]
    manifest: Mapping[str, Any]
    exported_count: int
    failed_count: int
    failed_candidate_ids: tuple[str, ...]


def build_completed_event(
    published: PublishedExport,
    *,
    message_id: str,
    job_id: str,
    occurred_at: str,
    idempotency_key: str,
    traceparent: str,
) -> bytes:
    """构造发往业务后端的完成事件，不把包字节或清单内容放进消息。"""
    _validate_uuid(message_id, "message_id")
    _validate_uuid(job_id, "sample_export_job_id")
    if not isinstance(occurred_at, str) or not occurred_at.endswith("Z"):
        raise ExportFailure("EVENT_TIME_INVALID", "完成事件时间必须是 UTC 字符串")
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 128:
        raise ExportFailure("EVENT_IDEMPOTENCY_INVALID", "完成事件幂等键长度非法")
    if not isinstance(traceparent, str) or not TRACEPARENT_PATTERN.fullmatch(traceparent):
        raise ExportFailure("EVENT_TRACE_INVALID", "完成事件 traceparent 不合法")
    if published.status not in {"SUCCEEDED", "FAILED"}:
        raise ExportFailure("EVENT_STATUS_INVALID", "未形成终态不能发布完成事件")
    package = _published_reference(
        published.package, "package", PACKAGE_MEDIA_TYPE, "sample-exports/"
    )
    manifest = _published_reference(
        published.manifest, "manifest", RESULT_MEDIA_TYPE, "sample-exports/"
    )
    payload = {
        "message_id": message_id,
        "occurred_at": occurred_at,
        "idempotency_key": idempotency_key,
        "traceparent": traceparent,
        "sample_export_job_id": job_id,
        "package": package,
        "manifest": manifest,
        "exported_count": published.exported_count,
        "failed_candidate_ids": sorted(published.failed_candidate_ids),
    }
    return canonical_json(payload)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def build_package(
    candidates: Sequence[CandidateInput],
    reader: ObjectReader,
    maximum_package_bytes: int,
) -> ExportBuildResult:
    if not candidates:
        raise ExportFailure("CANDIDATE_EMPTY", "导出候选不能为空")
    if maximum_package_bytes <= 0:
        raise ExportFailure("CONFIG_INVALID", "导出包大小上限必须大于 0")

    item_results: list[ItemResult] = []
    files: dict[str, bytes] = {}
    exported_ids: list[str] = []
    failed_ids: list[str] = []
    for candidate in candidates:
        try:
            _validate_candidate_id(candidate.candidate_id)
            candidate_files = _candidate_files(candidate, reader)
            records: list[dict[str, Any]] = []
            file_entries: list[dict[str, Any]] = []
            for name, data in sorted(candidate_files.items()):
                if name in files:
                    raise ExportFailure("PACKAGE_PATH_COLLISION", "导出包内部路径冲突")
                files[name] = data
                file_entries.append(
                    {
                        "path": name,
                        "sha256": sha256_bytes(data),
                        "size_bytes": len(data),
                    }
                )
            records.append({"candidate_id": candidate.candidate_id, "files": file_entries})
            item_results.append(
                ItemResult(candidate.candidate_id, "EXPORTED", tuple(file_entries))
            )
            exported_ids.append(candidate.candidate_id)
        except ExportFailure as failure:
            digest = sha256_bytes(f"{failure.code}:{failure}".encode("utf-8"))
            item_results.append(
                ItemResult(candidate.candidate_id, "FAILED", error_code=failure.code, error_detail_digest=digest)
            )
            failed_ids.append(candidate.candidate_id)

    manifest = {
        "format_version": "r7-sample-export/1",
        "media_policy": {
            "original": ["image/jpeg", "image/png"],
            "result": [RESULT_MEDIA_TYPE],
        },
        "items": [
            {
                "candidate_id": item.candidate_id,
                "status": item.status,
                **({"files": list(item.files)} if item.status == "EXPORTED" else {}),
                **(
                    {
                        "error_code": item.error_code,
                        "error_detail_digest": item.error_detail_digest,
                    }
                    if item.status == "FAILED"
                    else {}
                ),
            }
            for item in sorted(item_results, key=lambda value: value.candidate_id)
        ],
        "exported_count": len(exported_ids),
        "failed_count": len(failed_ids),
        "failed_candidate_ids": sorted(failed_ids),
    }
    manifest_bytes = canonical_json(manifest)
    files["manifest.json"] = manifest_bytes
    package_bytes = _zip_bytes(files)
    if len(package_bytes) > maximum_package_bytes:
        raise ExportFailure("PACKAGE_TOO_LARGE", "导出包超过配置大小上限")
    status = "SUCCEEDED" if not failed_ids else "FAILED"
    return ExportBuildResult(
        status,
        package_bytes,
        manifest_bytes,
        len(exported_ids),
        len(failed_ids),
        tuple(sorted(exported_ids)),
        tuple(sorted(failed_ids)),
        tuple(sorted(item_results, key=lambda value: value.candidate_id)),
    )


def publish_export(
    result: ExportBuildResult,
    bucket: str,
    package_key: str,
    manifest_key: str,
    writer: ObjectWriter,
) -> PublishedExport:
    if not bucket or not package_key.startswith("sample-exports/") or not manifest_key.startswith("sample-exports/"):
        raise ExportFailure("TARGET_INVALID", "导出目标必须使用 sample-exports/ 前缀")
    try:
        package_ref = writer.put(bucket, package_key, PACKAGE_MEDIA_TYPE, result.package_bytes)
        manifest_ref = writer.put(bucket, manifest_key, RESULT_MEDIA_TYPE, result.manifest_bytes)
    except RetryableExportFailure:
        raise
    except Exception as failure:  # noqa: BLE001 - 依赖故障必须由调度层重试/HOLD
        raise RetryableExportFailure("对象存储写入失败") from failure
    _validate_published_reference(package_ref, bucket, package_key, PACKAGE_MEDIA_TYPE, result.package_bytes)
    _validate_published_reference(manifest_ref, bucket, manifest_key, RESULT_MEDIA_TYPE, result.manifest_bytes)
    return PublishedExport(
        result.status,
        package_ref,
        manifest_ref,
        result.exported_count,
        result.failed_count,
        result.failed_candidate_ids,
    )


def _candidate_files(candidate: CandidateInput, reader: ObjectReader) -> dict[str, bytes]:
    snapshot = dict(candidate.source_snapshot)
    image = _object_reference(snapshot.get("image"), "image")
    if image["media_type"] not in ALLOWED_IMAGE_TYPES:
        raise ExportFailure("MEDIA_TYPE_UNSUPPORTED", "原图媒体类型不允许导出")
    original = _read_and_verify(reader, image, "ORIGINAL_OBJECT_INVALID")

    result_reference = snapshot.get("result_reference")
    result_payload: dict[str, Any]
    result_bytes: bytes | None = None
    if result_reference is not None:
        reference = _object_reference(result_reference, "result_reference")
        if reference["media_type"] != RESULT_MEDIA_TYPE:
            raise ExportFailure("RESULT_MEDIA_TYPE_INVALID", "结果对象必须是 JSON")
        result_bytes = _read_and_verify(reader, reference, "RESULT_OBJECT_INVALID")
        try:
            parsed = json.loads(result_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as failure:
            raise ExportFailure("RESULT_JSON_INVALID", "结果对象不是合法 JSON") from failure
        if not isinstance(parsed, dict):
            raise ExportFailure("RESULT_JSON_INVALID", "结果对象根必须是 JSON 对象")
        result_payload = parsed
    else:
        result_payload = {}

    versions = _versions(snapshot, result_payload)
    conclusion = result_payload.get("algorithm_outcome", snapshot.get("algorithm_outcome"))
    confidence = result_payload.get("confidence", snapshot.get("confidence"))
    regions = result_payload.get("defect_regions", snapshot.get("defect_regions"))
    region_count = result_payload.get("defect_region_count", snapshot.get("defect_region_count"))
    if conclusion is None or confidence is None or (regions is None and region_count is None):
        raise ExportFailure("EVIDENCE_INCOMPLETE", "缺少系统结论、置信度或缺陷区域摘要")

    metadata = {
        "candidate_id": candidate.candidate_id,
        "detection_time": snapshot.get("detection_time", snapshot.get("detection_updated_at")),
        "usage_stage": snapshot.get("usage_stage"),
        "source": snapshot.get("source", "MANUAL_BATCH"),
        "model_version": versions["model_version"],
        "pipeline_version": versions["pipeline_version"],
        "rules_version": versions["rules_version"],
        "system_conclusion": conclusion,
        "confidence": confidence,
        "defect_region_count": region_count if region_count is not None else len(regions),
        "defect_regions": regions if regions is not None else [],
        "employee_feedback": snapshot.get("employee_feedback"),
        "admin_feedback": snapshot.get("admin_feedback"),
        "source_references": {
            "image": _public_reference(image),
            **({"result": _public_reference(result_reference)} if result_reference is not None else {}),
        },
    }
    prefix = f"samples/{candidate.candidate_id}/"
    result: dict[str, bytes] = {
        prefix + "original" + ALLOWED_IMAGE_TYPES[image["media_type"]]: original,
        prefix + "record.json": canonical_json(metadata),
    }
    if result_bytes is not None:
        result[prefix + "result.json"] = result_bytes
    return result


def _versions(snapshot: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, str]:
    values = {
        "model_version": result.get("model_version", snapshot.get("model_version")),
        "pipeline_version": result.get("pipeline_version", snapshot.get("pipeline_version")),
        "rules_version": result.get(
            "rules_version", result.get("rule_version", snapshot.get("rules_version"))
        ),
    }
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise ExportFailure("VERSION_UNAVAILABLE", "无法取得完整模型、流水线和规则版本")
    return {key: value.strip() for key, value in values.items()}


def _object_reference(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ExportFailure("OBJECT_REFERENCE_INVALID", f"{name} 缺少对象引用")
    required = {"bucket", "object_key", "sha256", "size_bytes", "media_type"}
    if not set(value).issubset(required | {"object_version"}):
        raise ExportFailure("OBJECT_REFERENCE_INVALID", f"{name} 键结构无效")
    if not required.issubset(value):
        raise ExportFailure("OBJECT_REFERENCE_INVALID", f"{name} 缺少必填对象字段")
    bucket = value["bucket"]
    key = value["object_key"]
    sha = value["sha256"]
    size = value["size_bytes"]
    media_type = value["media_type"]
    if not isinstance(bucket, str) or not bucket or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,126}", bucket):
        raise ExportFailure("OBJECT_REFERENCE_INVALID", f"{name} 桶不合法")
    if not isinstance(key, str) or not key or key.startswith(("/", "http://", "https://")):
        raise ExportFailure("OBJECT_REFERENCE_INVALID", f"{name} 对象键不合法")
    if not isinstance(sha, str) or not SHA256_PATTERN.fullmatch(sha):
        raise ExportFailure("OBJECT_REFERENCE_INVALID", f"{name} SHA-256 不合法")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ExportFailure("OBJECT_REFERENCE_INVALID", f"{name} 大小不合法")
    if not isinstance(media_type, str) or not media_type:
        raise ExportFailure("OBJECT_REFERENCE_INVALID", f"{name} 媒体类型不合法")
    return dict(value)


def _read_and_verify(reader: ObjectReader, reference: Mapping[str, Any], error_code: str) -> bytes:
    try:
        data = reader.read(reference)
    except RetryableExportFailure:
        raise
    except Exception as failure:  # noqa: BLE001 - 读取故障必须进入 HOLD/重试
        raise RetryableExportFailure("对象存储读取失败") from failure
    if not isinstance(data, bytes):
        raise ExportFailure(error_code, "对象读取结果不是字节")
    if len(data) != reference["size_bytes"] or sha256_bytes(data) != reference["sha256"]:
        raise ExportFailure("OBJECT_HASH_CONFLICT", "对象大小或 SHA-256 与登记不一致")
    return data


def _public_reference(reference: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"bucket", "object_key", "object_version", "sha256", "size_bytes", "media_type"}
    return {key: reference[key] for key in allowed if key in reference}


def _validate_candidate_id(value: str) -> None:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as failure:
        raise ExportFailure("CANDIDATE_ID_INVALID", "候选标识不是合法 UUID") from failure
    if not UUID_PATTERN.fullmatch(value):
        raise ExportFailure("CANDIDATE_ID_INVALID", "候选标识版本不受支持")


def _validate_uuid(value: str, field: str) -> None:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as failure:
        raise ExportFailure("EVENT_UUID_INVALID", f"{field} 不是合法 UUID") from failure


def _published_reference(
    value: Mapping[str, Any],
    name: str,
    media_type: str,
    prefix: str,
) -> dict[str, Any]:
    reference = _object_reference(value, name)
    if reference["media_type"] != media_type or not reference["object_key"].startswith(prefix):
        raise ExportFailure("EVENT_REFERENCE_INVALID", f"{name} 引用不符合 R7 前缀或媒体类型")
    return _public_reference(reference)


def _zip_bytes(files: Mapping[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for name in sorted(files):
            if name.startswith("/") or ".." in name.split("/"):
                raise ExportFailure("PACKAGE_PATH_INVALID", "导出包内部路径不安全")
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            package.writestr(info, files[name])
    return output.getvalue()


def _validate_published_reference(
    value: Mapping[str, Any], bucket: str, key: str, media_type: str, data: bytes
) -> None:
    if not isinstance(value, Mapping) or value.get("bucket") != bucket or value.get("object_key") != key:
        raise RetryableExportFailure("对象存储返回的位置与目标不一致")
    if value.get("media_type") != media_type or value.get("size_bytes") != len(data):
        raise RetryableExportFailure("对象存储返回的大小或媒体类型不一致")
    if value.get("sha256") != sha256_bytes(data):
        raise RetryableExportFailure("对象存储返回的 SHA-256 不一致")
