#!/usr/bin/env python3
"""开发环境数据集构建执行端。

执行端领取业务库中处于 BUILDING 的数据集版本，读取并严格校验候选清单对象，
然后把成功任务推进到 VALIDATING。任何清单缺失、哈希冲突或结构问题都会明确
进入 REJECTED；临时连接故障保留为 BUILDING/HOLD，等待租约到期后重试。
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
WORKER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
ALLOWED_SPLITS = {"TRAIN", "VALIDATION", "TEST"}
DEFAULT_MAX_MANIFEST_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_SAMPLES = 1_000_000


@dataclass(frozen=True)
class BuildJob:
    dataset_version_id: str
    dataset_id: str
    version: str
    manifest_bucket: str
    manifest_object_key: str
    manifest_sha256: str
    expected_sample_count: int


@dataclass(frozen=True)
class BuildResult:
    sample_count: int
    stratification: Mapping[str, Any]


class BuildFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RetryableBuildFailure(BuildFailure):
    """临时依赖故障；任务保持 BUILDING 并在租约到期后重试。"""


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise BuildFailure("CONFIG_MISSING", f"缺少非空环境变量：{name}")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise BuildFailure("CONFIG_INVALID", f"环境变量包含非法字符：{name}")
    return value


def _sql_literal(value: str) -> str:
    if "\x00" in value:
        raise BuildFailure("DATABASE_VALUE_INVALID", "数据库参数包含空字符")
    return "'" + value.replace("'", "''") + "'"


def _json_b64(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def log_event(event: str, message: str, **fields: Any) -> None:
    payload = {
        "timestamp": utc_now(),
        "event": event,
        "message": message,
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


class PsqlDatabase:
    """通过开发 PostgreSQL 容器内的 psql 访问业务库。

    密码只通过标准输入送入容器，不出现在进程参数、日志或就绪文件中。
    """

    def __init__(
        self,
        container_id: str,
        password: str,
        worker_id: str,
        lease_seconds: int,
        docker_command: str = "docker",
    ) -> None:
        if not container_id or any(char.isspace() for char in container_id):
            raise BuildFailure("CONFIG_INVALID", "PostgreSQL 容器标识不合法")
        if not WORKER_ID_PATTERN.fullmatch(worker_id):
            raise BuildFailure("CONFIG_INVALID", "数据构建执行端标识不合法")
        if lease_seconds < 10 or lease_seconds > 3600:
            raise BuildFailure("CONFIG_INVALID", "任务租约必须介于 10 到 3600 秒")
        self.container_id = container_id
        self.password = password
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.docker_command = docker_command

    def _query(self, sql: str) -> str:
        shell = """
IFS= read -r PGPASSWORD
export PGPASSWORD
exec psql \
  --host 127.0.0.1 \
  --username tool_defect \
  --dbname tool_defect \
  --no-psqlrc \
  --set ON_ERROR_STOP=1 \
  --tuples-only \
  --no-align \
  --quiet
""".strip()
        try:
            completed = subprocess.run(
                [
                    self.docker_command,
                    "exec",
                    "--interactive",
                    "--user",
                    "postgres",
                    self.container_id,
                    "sh",
                    "-c",
                    shell,
                ],
                input=self.password + "\n" + sql,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RetryableBuildFailure(
                "DATABASE_UNAVAILABLE",
                f"无法执行数据库命令：{type(exc).__name__}",
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip().splitlines()
            message = detail[-1][:300] if detail else "psql 返回非零状态"
            raise RetryableBuildFailure("DATABASE_UNAVAILABLE", message)
        return completed.stdout.strip()

    def health(self) -> None:
        if self._query("SELECT 1;\n") != "1":
            raise RetryableBuildFailure("DATABASE_UNHEALTHY", "数据库健康查询未返回 1")

    def claim(self) -> Optional[BuildJob]:
        worker = _sql_literal(self.worker_id)
        sql = f"""
WITH next_job AS (
    SELECT dataset_version_id
    FROM dataset_version
    WHERE status = 'BUILDING'
      AND (
        build_claimed_at IS NULL
        OR build_claimed_at < now() - make_interval(secs => {self.lease_seconds})
      )
    ORDER BY created_at, dataset_version_id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
), claimed AS (
    UPDATE dataset_version AS target
    SET build_worker_id = {worker},
        build_claimed_at = now(),
        record_version = target.record_version + 1
    FROM next_job
    WHERE target.dataset_version_id = next_job.dataset_version_id
    RETURNING target.dataset_version_id, target.dataset_id, target.version,
              target.manifest_bucket, target.manifest_object_key,
              target.manifest_sha256, target.sample_count
)
SELECT COALESCE((SELECT row_to_json(claimed)::text FROM claimed), '');
"""
        raw = self._query(sql)
        if not raw:
            return None
        try:
            row = json.loads(raw)
            job = BuildJob(
                dataset_version_id=str(row["dataset_version_id"]),
                dataset_id=str(row["dataset_id"]),
                version=str(row["version"]),
                manifest_bucket=str(row["manifest_bucket"] or ""),
                manifest_object_key=str(row["manifest_object_key"] or ""),
                manifest_sha256=str(row["manifest_sha256"] or ""),
                expected_sample_count=int(row["sample_count"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RetryableBuildFailure(
                "DATABASE_RESPONSE_INVALID",
                "数据库返回的构建任务格式不合法",
            ) from exc
        if not UUID_PATTERN.fullmatch(job.dataset_version_id):
            raise RetryableBuildFailure("DATABASE_RESPONSE_INVALID", "数据集版本标识不合法")
        return job

    def complete(self, job: BuildJob, result: BuildResult) -> bool:
        evidence = _json_b64(result.stratification)
        sql = f"""
UPDATE dataset_version
SET sample_count = {result.sample_count},
    stratification = convert_from(decode({_sql_literal(evidence)}, 'base64'), 'UTF8')::jsonb,
    status = 'VALIDATING',
    build_worker_id = NULL,
    build_claimed_at = NULL,
    record_version = record_version + 1
WHERE dataset_version_id = {_sql_literal(job.dataset_version_id)}::uuid
  AND status = 'BUILDING'
  AND build_worker_id = {_sql_literal(self.worker_id)}
RETURNING 1;
"""
        return self._query(sql) == "1"

    def reject(self, job: BuildJob, failure: BuildFailure) -> bool:
        evidence = _json_b64(_failure_evidence(self.worker_id, failure, "FAILED"))
        sql = f"""
UPDATE dataset_version
SET stratification = convert_from(decode({_sql_literal(evidence)}, 'base64'), 'UTF8')::jsonb,
    status = 'REJECTED',
    build_worker_id = NULL,
    build_claimed_at = NULL,
    record_version = record_version + 1
WHERE dataset_version_id = {_sql_literal(job.dataset_version_id)}::uuid
  AND status = 'BUILDING'
  AND build_worker_id = {_sql_literal(self.worker_id)}
RETURNING 1;
"""
        return self._query(sql) == "1"

    def hold(self, job: BuildJob, failure: BuildFailure) -> bool:
        evidence = _json_b64(_failure_evidence(self.worker_id, failure, "HOLD"))
        sql = f"""
UPDATE dataset_version
SET stratification = convert_from(decode({_sql_literal(evidence)}, 'base64'), 'UTF8')::jsonb,
    build_claimed_at = now(),
    record_version = record_version + 1
WHERE dataset_version_id = {_sql_literal(job.dataset_version_id)}::uuid
  AND status = 'BUILDING'
  AND build_worker_id = {_sql_literal(self.worker_id)}
RETURNING 1;
"""
        return self._query(sql) == "1"


class S3ObjectStorage:
    """仅使用标准库实现的 S3 签名读取客户端。"""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        maximum_bytes: int = DEFAULT_MAX_MANIFEST_BYTES,
    ) -> None:
        parsed = urllib.parse.urlsplit(endpoint.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise BuildFailure("CONFIG_INVALID", "对象存储端点必须是 HTTP 或 HTTPS 地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise BuildFailure("CONFIG_INVALID", "对象存储端点不能包含凭据、查询或片段")
        if not access_key or not secret_key:
            raise BuildFailure("CONFIG_MISSING", "对象存储凭据不能为空")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", region):
            raise BuildFailure("CONFIG_INVALID", "对象存储区域不合法")
        if maximum_bytes < 1024 or maximum_bytes > 512 * 1024 * 1024:
            raise BuildFailure("CONFIG_INVALID", "候选清单大小限制不合法")
        self.endpoint = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
        )
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.maximum_bytes = maximum_bytes

    def health(self) -> None:
        request = urllib.request.Request(
            self.endpoint + "/minio/health/ready",
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                if response.status != 200:
                    raise RetryableBuildFailure(
                        "OBJECT_STORAGE_UNHEALTHY",
                        f"对象存储健康检查返回 {response.status}",
                    )
        except RetryableBuildFailure:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise RetryableBuildFailure(
                "OBJECT_STORAGE_UNAVAILABLE",
                f"对象存储健康检查失败：{type(exc).__name__}",
            ) from exc

    def fetch(self, bucket: str, object_key: str) -> bytes:
        if not BUCKET_PATTERN.fullmatch(bucket):
            raise BuildFailure("MANIFEST_REFERENCE_INVALID", "候选清单桶名不合法")
        key_parts = object_key.split("/")
        if (
            not object_key
            or object_key.startswith("/")
            or any(part in {"", ".", ".."} for part in key_parts)
            or any(ord(char) < 32 for char in object_key)
        ):
            raise BuildFailure("MANIFEST_REFERENCE_INVALID", "候选清单对象键不合法")
        encoded_path = "/" + urllib.parse.quote(
            bucket + "/" + object_key,
            safe="/-_.~",
        )
        request = self._signed_request(encoded_path)
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                length = response.headers.get("Content-Length")
                if length is not None and int(length) > self.maximum_bytes:
                    raise BuildFailure("MANIFEST_TOO_LARGE", "候选清单超过大小上限")
                payload = response.read(self.maximum_bytes + 1)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise BuildFailure("MANIFEST_NOT_FOUND", "候选清单对象不存在") from exc
            if 400 <= exc.code < 500:
                raise BuildFailure(
                    "MANIFEST_READ_DENIED",
                    f"候选清单读取被拒绝：HTTP {exc.code}",
                ) from exc
            raise RetryableBuildFailure(
                "OBJECT_STORAGE_UNAVAILABLE",
                f"对象存储返回 HTTP {exc.code}",
            ) from exc
        except (OSError, urllib.error.URLError, ValueError) as exc:
            raise RetryableBuildFailure(
                "OBJECT_STORAGE_UNAVAILABLE",
                f"候选清单读取失败：{type(exc).__name__}",
            ) from exc
        if len(payload) > self.maximum_bytes:
            raise BuildFailure("MANIFEST_TOO_LARGE", "候选清单超过大小上限")
        return payload

    def _signed_request(self, encoded_path: str) -> urllib.request.Request:
        parsed = urllib.parse.urlsplit(self.endpoint)
        now = dt.datetime.now(dt.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(b"").hexdigest()
        canonical_headers = (
            f"host:{parsed.netloc}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            ["GET", encoded_path, "", canonical_headers, signed_headers, payload_hash]
        )
        scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signing_key = _signature_key(self.secret_key, date_stamp, self.region, "s3")
        signature = hmac.new(
            signing_key,
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return urllib.request.Request(
            self.endpoint + encoded_path,
            headers={
                "Authorization": authorization,
                "x-amz-content-sha256": payload_hash,
                "x-amz-date": amz_date,
            },
            method="GET",
        )


def _hmac_sha256(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def _signature_key(secret: str, date: str, region: str, service: str) -> bytes:
    date_key = _hmac_sha256(("AWS4" + secret).encode("utf-8"), date)
    region_key = _hmac_sha256(date_key, region)
    service_key = _hmac_sha256(region_key, service)
    return _hmac_sha256(service_key, "aws4_request")


def verify_manifest(
    payload: bytes,
    job: BuildJob,
    worker_id: str,
    maximum_samples: int = DEFAULT_MAX_SAMPLES,
) -> BuildResult:
    if not SHA256_PATTERN.fullmatch(job.manifest_sha256):
        raise BuildFailure("MANIFEST_REFERENCE_INVALID", "候选清单预期哈希不合法")
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != job.manifest_sha256:
        raise BuildFailure("MANIFEST_HASH_CONFLICT", "候选清单对象哈希与登记值不一致")
    if job.expected_sample_count <= 0:
        raise BuildFailure("MANIFEST_EMPTY", "候选清单不能为空")
    if job.expected_sample_count > maximum_samples:
        raise BuildFailure("MANIFEST_SAMPLE_LIMIT", "候选清单样本数超过执行端上限")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BuildFailure("MANIFEST_ENCODING_INVALID", "候选清单不是 UTF-8 文本") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = set(reader.fieldnames or [])
    key_field = "sample_key" if "sample_key" in fields else "sample_id"
    required = {key_field, "content_sha256", "split", "group_key", "label"}
    missing = sorted(required - fields)
    if missing or key_field not in {"sample_key", "sample_id"}:
        raise BuildFailure(
            "MANIFEST_COLUMNS_MISSING",
            "候选清单缺少字段：" + ",".join(missing or ["sample_key_or_sample_id"]),
        )

    sample_keys = set()
    content_splits: Dict[str, set] = {}
    group_splits: Dict[str, set] = {}
    split_counts: Dict[str, int] = {}
    label_counts: Dict[str, int] = {}
    row_count = 0
    for row_number, row in enumerate(reader, start=2):
        row_count += 1
        if row_count > maximum_samples:
            raise BuildFailure("MANIFEST_SAMPLE_LIMIT", "候选清单实际样本数超过执行端上限")
        sample_key = (row.get(key_field) or "").strip()
        content_sha = (row.get("content_sha256") or "").strip().lower()
        split = (row.get("split") or "").strip().upper()
        group_key = (row.get("group_key") or "").strip()
        label = (row.get("label_name") or row.get("label") or "").strip()
        if not sample_key or len(sample_key) > 256:
            raise BuildFailure("MANIFEST_ROW_INVALID", f"第 {row_number} 行样本键不合法")
        if sample_key in sample_keys:
            raise BuildFailure("MANIFEST_DUPLICATE_SAMPLE", f"样本键重复：{sample_key}")
        if not SHA256_PATTERN.fullmatch(content_sha):
            raise BuildFailure("MANIFEST_ROW_INVALID", f"第 {row_number} 行内容哈希不合法")
        if split not in ALLOWED_SPLITS:
            raise BuildFailure("MANIFEST_ROW_INVALID", f"第 {row_number} 行划分不合法")
        if not group_key or len(group_key) > 256:
            raise BuildFailure("MANIFEST_ROW_INVALID", f"第 {row_number} 行组标识不合法")
        if not label or len(label) > 64:
            raise BuildFailure("MANIFEST_ROW_INVALID", f"第 {row_number} 行标签不合法")
        sample_keys.add(sample_key)
        content_splits.setdefault(content_sha, set()).add(split)
        group_splits.setdefault(group_key, set()).add(split)
        split_counts[split] = split_counts.get(split, 0) + 1
        label_counts[label] = label_counts.get(label, 0) + 1

    if row_count != job.expected_sample_count:
        raise BuildFailure(
            "MANIFEST_SAMPLE_COUNT_CONFLICT",
            f"候选清单登记 {job.expected_sample_count} 条，实际 {row_count} 条",
        )
    if len(content_splits) != row_count:
        raise BuildFailure(
            "MANIFEST_DUPLICATE_CONTENT",
            f"候选清单包含 {row_count - len(content_splits)} 个重复内容哈希",
        )
    cross_split_groups = sorted(
        group for group, splits in group_splits.items() if len(splits) > 1
    )
    if cross_split_groups:
        raise BuildFailure(
            "MANIFEST_GROUP_LEAKAGE",
            "同组样本跨越数据划分：" + ",".join(cross_split_groups[:5]),
        )
    return BuildResult(
        sample_count=row_count,
        stratification={
            "split_counts": dict(sorted(split_counts.items())),
            "label_counts": dict(sorted(label_counts.items())),
            "builder": {
                "state": "PASSED",
                "worker_id": worker_id,
                "verified_at": utc_now(),
                "manifest_sha256": actual_sha256,
                "manifest_bytes": len(payload),
                "unique_content_hashes": len(content_splits),
            },
        },
    )


def _failure_evidence(worker_id: str, failure: BuildFailure, state: str) -> Mapping[str, Any]:
    return {
        "builder": {
            "state": state,
            "worker_id": worker_id,
            "failed_at": utc_now(),
            "error_code": failure.code,
            "message": str(failure)[:500],
        }
    }


def process_one(database: Any, storage: Any, worker_id: str) -> str:
    job = database.claim()
    if job is None:
        return "IDLE"
    log_event(
        "dataset.build.claimed",
        "已领取数据集构建任务",
        dataset_version_id=job.dataset_version_id,
        version=job.version,
    )
    try:
        payload = storage.fetch(job.manifest_bucket, job.manifest_object_key)
        result = verify_manifest(payload, job, worker_id)
        if not database.complete(job, result):
            raise RetryableBuildFailure("BUILD_LEASE_LOST", "构建完成时任务租约已失效")
    except RetryableBuildFailure as failure:
        try:
            database.hold(job, failure)
        except RetryableBuildFailure:
            pass
        log_event(
            "dataset.build.hold",
            str(failure),
            dataset_version_id=job.dataset_version_id,
            error_code=failure.code,
        )
        return "HOLD"
    except BuildFailure as failure:
        if not database.reject(job, failure):
            raise RetryableBuildFailure("BUILD_LEASE_LOST", "构建失败落库时任务租约已失效")
        log_event(
            "dataset.build.rejected",
            str(failure),
            dataset_version_id=job.dataset_version_id,
            error_code=failure.code,
        )
        return "REJECTED"
    log_event(
        "dataset.build.validating",
        "候选清单校验通过，数据集版本进入验证中",
        dataset_version_id=job.dataset_version_id,
        sample_count=result.sample_count,
    )
    return "VALIDATING"


def _write_ready_file(path: Path, worker_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {"status": "READY", "worker_id": worker_id, "ready_at": utc_now()},
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _integer_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise BuildFailure("CONFIG_INVALID", f"环境变量必须是整数：{name}") from exc


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="运行数据集构建常驻执行端")
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    try:
        worker_id = os.environ.get("TD_DATASET_BUILDER_WORKER_ID", "dataset-builder-development")
        poll_seconds = _integer_env("TD_DATASET_BUILDER_POLL_SECONDS", 2)
        lease_seconds = _integer_env("TD_DATASET_BUILDER_LEASE_SECONDS", 30)
        maximum_bytes = _integer_env(
            "TD_DATASET_BUILDER_MAX_MANIFEST_BYTES",
            DEFAULT_MAX_MANIFEST_BYTES,
        )
        if poll_seconds < 1 or poll_seconds > 60:
            raise BuildFailure("CONFIG_INVALID", "轮询间隔必须介于 1 到 60 秒")
        database = PsqlDatabase(
            _required_env("TD_DATASET_BUILDER_POSTGRES_CONTAINER"),
            _required_env("TD_DATABASE_PASSWORD"),
            worker_id,
            lease_seconds,
        )
        storage = S3ObjectStorage(
            _required_env("TD_S3_ENDPOINT"),
            _required_env("TD_S3_ACCESS_KEY"),
            _required_env("TD_S3_SECRET_KEY"),
            os.environ.get("TD_S3_REGION", "us-east-1"),
            maximum_bytes,
        )
        database.health()
        storage.health()
    except BuildFailure as failure:
        log_event("dataset.builder.start_failed", str(failure), error_code=failure.code)
        return 2

    ready_file = args.ready_file
    if ready_file is not None:
        _write_ready_file(ready_file, worker_id)
    log_event("dataset.builder.ready", "数据集构建执行端已就绪", worker_id=worker_id)

    stopping = False

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    while not stopping:
        try:
            outcome = process_one(database, storage, worker_id)
        except RetryableBuildFailure as failure:
            log_event("dataset.builder.dependency_hold", str(failure), error_code=failure.code)
            outcome = "HOLD"
        if args.once:
            return 0
        if outcome in {"IDLE", "HOLD"}:
            deadline = time.monotonic() + poll_seconds
            while not stopping and time.monotonic() < deadline:
                time.sleep(min(0.25, deadline - time.monotonic()))

    log_event("dataset.builder.stopped", "数据集构建执行端已停止", worker_id=worker_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
