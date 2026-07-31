#!/usr/bin/env python3
"""P7-03 生产数据迁移编排器

读取 P6-01 受控输出与 data/images/、data/masks/，将历史基线数据迁移至：
- PostgreSQL（通过直接 JDBC 或 REST API 注册引用记录）
- S3 兼容对象存储（上传图片和掩码）

环境变量配置:
  DB_URL, DB_USER, DB_PASSWORD, S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
IMAGES_DIR = DATA_DIR / "images"
MASKS_DIR = DATA_DIR / "masks"
CONTROLLED_OUTPUT = REPO_ROOT / "jobs" / "artifact-migrator" / "controlled-output"
OUTPUT_DIR = REPO_ROOT / "jobs" / "production-migration" / "output"

HASH_CHUNK = 65536

MIGRATION_BATCH_SIZE_DEFAULT = 50
VERIFY_SAMPLE_SIZE_DEFAULT = 20


def sha256_hex(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def env_required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"缺少必需环境变量: {name}")
    return value


def env_optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class SourceRecord:
    sample_id: str
    image_path: str
    mask_path: str
    label: int
    label_name: str
    split: str
    image_sha256: str
    image_size_bytes: int
    image_width: int
    image_height: int
    image_channels: int
    mask_sha256: str
    mask_size_bytes: int
    mask_has_content: str
    family_key: str
    errors: int


@dataclass
class MigrationReport:
    phase: str
    status: str
    details: Dict[str, Any]
    errors: List[str]


class S3Client:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, region: str = "us-east-1"):
        self._endpoint = endpoint.rstrip("/")
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._region = region
        self._uploaded: Dict[str, Dict[str, Any]] = {}

    def _sign(self, method: str, key: str, headers: Dict[str, str], body: bytes = b"") -> Dict[str, str]:
        import hmac
        from urllib.parse import urlparse

        parsed = urlparse(self._endpoint)
        host = parsed.netloc or parsed.path
        service = "s3"
        scope_date = datetime.utcnow().strftime("%Y%m%d")
        credential_scope = f"{scope_date}/{self._region}/{service}/aws4_request"

        content_hash = sha256_bytes(body)
        headers["x-amz-content-sha256"] = content_hash
        headers["host"] = host

        signed_headers = ";".join(sorted(h.lower() for h in headers))
        canonical_headers = "".join(
            f"{k.lower()}:{headers[k].strip()}\n" for k in sorted(headers, key=str.lower)
        )
        canonical_request = "\n".join([
            method,
            f"/{key}" if not key.startswith("/") else key,
            "",
            canonical_headers,
            signed_headers,
            content_hash,
        ])
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256",
            datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
            credential_scope,
            sha256_text(canonical_request),
        ])

        def sign_key(key_data: bytes, msg: str) -> bytes:
            return hmac.new(key_data, msg.encode("utf-8"), hashlib.sha256).digest()

        k_date = sign_key(b"AWS4" + self._secret_key.encode("utf-8"), scope_date)
        k_region = sign_key(k_date, self._region)
        k_service = sign_key(k_region, service)
        k_signing = sign_key(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        authorization = (
            f"AWS4-HMAC-SHA256 Credential={self._access_key}/{credential_scope},"
            f"SignedHeaders={signed_headers},Signature={signature}"
        )
        headers["Authorization"] = authorization
        return headers

    def put_object(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> Dict[str, Any]:
        import urllib.request

        url = f"{self._endpoint}/{self._bucket}/{key}"
        headers: Dict[str, str] = {
            "Content-Type": content_type,
            "x-amz-date": datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        }
        headers = self._sign("PUT", f"/{self._bucket}/{key}", headers, data)

        req = urllib.request.Request(url, data=data, method="PUT")
        for k, v in headers.items():
            req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = {"status": resp.status, "key": key, "sha256": sha256_bytes(data)}
                self._uploaded[key] = result
                return result
        except urllib.error.HTTPError as e:
            return {"status": e.code, "key": key, "error": str(e)}

    def head_object(self, key: str) -> Optional[Dict[str, Any]]:
        import urllib.request

        url = f"{self._endpoint}/{self._bucket}/{key}"
        headers: Dict[str, str] = {
            "x-amz-date": datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        }
        headers = self._sign("HEAD", f"/{self._bucket}/{key}", headers)

        req = urllib.request.Request(url, method="HEAD")
        for k, v in headers.items():
            req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return {"key": key, "status": resp.status, "content_length": resp.headers.get("Content-Length")}
        except urllib.error.HTTPError as e:
            return None

    def delete_objects(self, keys: List[str]) -> Dict[str, Any]:
        import urllib.request

        url = f"{self._endpoint}/{self._bucket}?delete"
        body = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<Delete>'
                + "".join(f"<Object><Key>{k}</Key></Object>" for k in keys)
                + '</Delete>').encode("utf-8")

        headers: Dict[str, str] = {
            "Content-Type": "application/xml",
            "x-amz-date": datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
            "Content-MD5": hashlib.md5(body).digest().hex(),
        }
        headers = self._sign("POST", f"/{self._bucket}?delete", headers, body)

        req = urllib.request.Request(url, data=body, method="POST")
        for k, v in headers.items():
            req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return {"status": resp.status, "deleted": len(keys)}
        except urllib.error.HTTPError as e:
            return {"status": e.code, "error": str(e)}

    def put_file(self, key: str, file_path: Path, content_type: str = "application/octet-stream") -> Dict[str, Any]:
        data = file_path.read_bytes()
        result = self.put_object(key, data, content_type)
        result["source_path"] = str(file_path)
        result["source_sha256"] = sha256_hex(file_path)
        return result


class DatabaseClient:
    def __init__(self, db_url: str, db_user: str, db_password: str):
        self._db_url = db_url
        self._db_user = db_user
        self._db_password = db_password
        self._dry_run = False

    def set_dry_run(self, enabled: bool) -> None:
        self._dry_run = enabled

    def _parse_db_url(self) -> Dict[str, str]:
        pattern = r"^(?:jdbc:)?postgres(?:ql)?://([^:]+):(\d+)/(.+)$"
        for variant in [self._db_url, self._db_url.replace("jdbc:postgresql://", "postgresql://")]:
            m = re.match(pattern, variant)
            if m:
                return {"host": m.group(1), "port": m.group(2), "database": m.group(3)}
        return {"host": "localhost", "port": "5432", "database": "tool_defect"}

    def execute_sql(self, sql: str, params: Optional[tuple] = None) -> Any:
        if self._dry_run:
            return None
        try:
            import psycopg2
        except ImportError:
            return None
        parsed = self._parse_db_url()
        conn = psycopg2.connect(
            host=parsed["host"],
            port=parsed["port"],
            dbname=parsed["database"],
            user=self._db_user,
            password=self._db_password,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description:
                    return cur.fetchall()
            conn.commit()
        finally:
            conn.close()
        return None

    def query_one(self, sql: str, params: Optional[tuple] = None) -> Any:
        result = self.execute_sql(sql, params)
        if result and len(result) > 0:
            return result[0]
        return None

    def query_count(self, table: str, where: str = "1=1") -> int:
        result = self.query_one(f"SELECT COUNT(*) FROM {table} WHERE {where}")
        if result:
            return int(result[0])
        return -1

    def row_exists(self, table: str, where: str, params: Optional[tuple] = None) -> bool:
        result = self.execute_sql(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", params)
        return bool(result)


class RestApiClient:
    def __init__(self, base_url: str, api_key: str = ""):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        import urllib.request

        url = f"{self._base_url}{path}"
        body = json.dumps(data).encode("utf-8")
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(url, data=body, method="POST")
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {"error": str(e), "status": e.code}

    def get(self, path: str) -> Dict[str, Any]:
        import urllib.request

        url = f"{self._base_url}{path}"
        headers: Dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(url, method="GET")
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {"error": str(e), "status": e.code}


def load_manifest_csv(csv_path: Path) -> List[SourceRecord]:
    records: List[SourceRecord] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(SourceRecord(
                sample_id=row["sample_id"],
                image_path=row["image_path"],
                mask_path=row["mask_path"],
                label=int(row["label"]),
                label_name=row["label_name"],
                split=row["split"],
                image_sha256=row["image_sha256"],
                image_size_bytes=int(row["image_size_bytes"]),
                image_width=int(row["image_width"]),
                image_height=int(row["image_height"]),
                image_channels=int(row["image_channels"]),
                mask_sha256=row["mask_sha256"],
                mask_size_bytes=int(row["mask_size_bytes"]),
                mask_has_content=row["mask_has_content"],
                family_key=row["family_key"],
                errors=int(row["errors"]),
            ))
    return records


def load_checksums(checksum_path: Path) -> Dict[str, str]:
    checksums: Dict[str, str] = {}
    if not checksum_path.exists():
        return checksums
    for line in checksum_path.read_text().strip().split("\n"):
        if line.strip():
            parts = line.split("  ", 1)
            if len(parts) == 2:
                checksums[parts[1]] = parts[0]
    return checksums


def load_summary() -> Dict[str, Any]:
    with open(CONTROLLED_OUTPUT / "summary.json") as f:
        return json.load(f)


def verify_source_integrity(records: List[SourceRecord], checksums: Dict[str, str]) -> Dict[str, Any]:
    passed = 0
    failed = 0
    failures: List[Dict[str, str]] = []

    for rec in records:
        if rec.errors > 0:
            failures.append({"sample_id": rec.sample_id, "reason": f"manifest_error_count={rec.errors}"})
            failed += 1
            continue

        img_path = DATA_DIR / rec.image_path
        if img_path.exists():
            actual = sha256_hex(img_path)
            if rec.image_sha256 and actual != rec.image_sha256:
                failures.append({"sample_id": rec.sample_id, "reason": f"image_sha256_mismatch: {actual[:16]}... vs {rec.image_sha256[:16]}..."})
                failed += 1
                continue
        else:
            failures.append({"sample_id": rec.sample_id, "reason": f"image_missing: {rec.image_path}"})
            failed += 1
            continue

        mask_path = DATA_DIR / rec.mask_path
        if mask_path.exists():
            actual = sha256_hex(mask_path)
            if rec.mask_sha256 and actual != rec.mask_sha256:
                failures.append({"sample_id": rec.sample_id, "reason": f"mask_sha256_mismatch: {actual[:16]}... vs {rec.mask_sha256[:16]}..."})
                failed += 1
                continue
        else:
            failures.append({"sample_id": rec.sample_id, "reason": f"mask_missing: {rec.mask_path}"})
            failed += 1
            continue

        passed += 1

    return {"total": len(records), "passed": passed, "failed": failed, "failures": failures}


def generate_object_key(kind: str, sample_id: str, ext: str) -> str:
    parts = sample_id.split("/")
    if len(parts) == 2:
        category, filename = parts
    else:
        category, filename = "unknown", sample_id
    capture_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"capture/{sample_id}"))
    now = datetime.now(timezone.utc)
    return f"capture/{now.year:04d}/{now.month:02d}/{now.day:02d}/{capture_id}/{kind.lower()}/{filename}{ext}"


def migrate_objects_to_s3(s3: S3Client, records: List[SourceRecord], dry_run: bool) -> Dict[str, Any]:
    uploaded: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    total_bytes = 0

    for i, rec in enumerate(records):
        if rec.errors > 0:
            continue

        img_path = DATA_DIR / rec.image_path
        if img_path.exists():
            ext = img_path.suffix.lower()
            key = generate_object_key("RAW", rec.sample_id, ext)
            if dry_run:
                uploaded.append({"key": key, "source": rec.image_path, "sha256": rec.image_sha256, "dry_run": True})
                total_bytes += rec.image_size_bytes
            else:
                result = s3.put_file(key, img_path, "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png")
                if result.get("status") in (200, 201):
                    uploaded.append({"key": key, "source": rec.image_path, "sha256": result.get("sha256", ""), "size": rec.image_size_bytes})
                    total_bytes += rec.image_size_bytes
                else:
                    failures.append({"sample_id": rec.sample_id, "file": "image", "error": str(result.get("error", result))})

        mask_path = DATA_DIR / rec.mask_path
        if mask_path.exists():
            ext = mask_path.suffix.lower()
            key = generate_object_key("DEFECT_MASK", rec.sample_id, ext)
            if dry_run:
                uploaded.append({"key": key, "source": rec.mask_path, "sha256": rec.mask_sha256, "dry_run": True})
                total_bytes += rec.mask_size_bytes
            else:
                result = s3.put_file(key, mask_path, "image/png")
                if result.get("status") in (200, 201):
                    uploaded.append({"key": key, "source": rec.mask_path, "sha256": result.get("sha256", ""), "size": rec.mask_size_bytes})
                    total_bytes += rec.mask_size_bytes
                else:
                    failures.append({"sample_id": rec.sample_id, "file": "mask", "error": str(result.get("error", result))})

    return {"uploaded": len(uploaded), "failed": len(failures), "failures": failures, "total_bytes": total_bytes}


def register_database_references(db: DatabaseClient, api: Optional[RestApiClient], records: List[SourceRecord], baseline_records: List[SourceRecord], dry_run: bool) -> Dict[str, Any]:
    if dry_run:
        return {
            "production_lines": 1, "stations": 1, "devices": 1,
            "capture_recipes": 2, "capture_events": 360, "image_objects": 720,
            "datasets": 1, "dataset_versions": 2, "dataset_samples": len(records),
            "models": 1, "model_versions": 3,
            "sys_users": 1,
            "dry_run": True,
        }
    raise NotImplementedError(
        "production database registration is not implemented; "
        "dry-run counts must not be treated as migrated facts"
    )


def verify_migration_counts(source_records: int, db: DatabaseClient, dry_run: bool) -> Dict[str, Any]:
    if dry_run:
        return {"image_object_count": -1, "capture_event_count": -1, "dataset_version_count": -1, "dry_run": True}

    image_count = db.query_count("image_object")
    capture_count = db.query_count("capture_event")
    dataset_version_count = db.query_count("dataset_version")
    model_version_count = db.query_count("model_version")

    return {
        "image_object_count": image_count,
        "expected_images": source_records * 2,
        "capture_event_count": capture_count,
        "expected_captures": source_records,
        "dataset_version_count": dataset_version_count,
        "expected_dataset_versions": 2,
        "model_version_count": model_version_count,
        "expected_model_versions": 3,
        "all_match": (
            image_count == source_records * 2
            and capture_count == source_records
            and dataset_version_count == 2
            and model_version_count == 3
        ),
    }


def source_is_approved(source_summary: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """判断受控源是否明确允许进入生产迁移。"""

    blockers: List[str] = []
    if source_summary.get("overall_status") != "COMPLETE":
        blockers.append(f"source_overall_status={source_summary.get('overall_status', 'MISSING')}")
    if source_summary.get("production_claim_allowed") is not True:
        blockers.append("source_production_claim_not_allowed")
    manifests = source_summary.get("manifests")
    baseline = manifests.get("baseline-180") if isinstance(manifests, dict) else None
    if not isinstance(baseline, dict):
        blockers.append("baseline_manifest_summary_missing")
    else:
        if baseline.get("status") != "COMPLETE":
            blockers.append(f"baseline_status={baseline.get('status', 'MISSING')}")
        for field in (
            "file_errors",
            "cross_split_issues",
            "family_leak_issues",
            "label_consistency_issues",
        ):
            if baseline.get(field) != 0:
                blockers.append(f"baseline_{field}={baseline.get(field, 'MISSING')}")
    return not blockers, blockers


def generate_report(
    phases: Dict[str, MigrationReport],
    summary: Dict[str, Any],
    *,
    source_summary: Dict[str, Any],
    migration_id: str = "",
    execution_mode: str = "UNKNOWN",
) -> Dict[str, Any]:
    source_approved, _ = source_is_approved(source_summary)
    report = {
        "schema_version": "tool-defect-production-migration/v1",
        "migrator_version": "2.0.0",
        "migration_id": migration_id,
        "execution_mode": execution_mode,
        "source_type": "REAL_PRODUCTION" if execution_mode == "EXECUTE" else "NON_PRODUCTION",
        "production_claim_allowed": (
            source_approved
            and execution_mode == "EXECUTE"
            and summary.get("overall_status") == "COMPLETE"
        ),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_summary": source_summary,
        "phases": {name: {"status": r.status, "details": r.details, "errors": r.errors} for name, r in phases.items()},
        "summary": summary,
    }
    return report


def summarize_phases(
    phases: Dict[str, MigrationReport],
    *,
    execution_mode: str,
) -> Dict[str, Any]:
    required = {"verify_source", "migrate_objects", "register_database", "verify_counts"}
    missing = sorted(required.difference(phases))
    statuses = {name: report.status for name, report in phases.items()}
    failed = sum(1 for report in phases.values() if report.status == "FAILED")
    passed = sum(1 for report in phases.values() if report.status == "PASSED")
    skipped = sum(
        1
        for report in phases.values()
        if report.status in {"SKIPPED", "DRY_RUN", "BLOCKED"}
    )
    complete = (
        execution_mode == "EXECUTE"
        and not missing
        and all(statuses.get(name) == "PASSED" for name in required)
    )
    overall_status = "COMPLETE" if complete else "FAILED" if failed else "BLOCKED"
    return {
        "overall_status": overall_status,
        "total_phases": len(phases),
        "passed_phases": passed,
        "failed_phases": failed,
        "skipped_or_blocked_phases": skipped,
        "missing_required_phases": missing,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P7-03 生产数据迁移")
    parser.add_argument("--dry-run", action="store_true", help="仅验证不写入")
    parser.add_argument("--rollback", action="store_true", help="拒绝无作用域回滚并输出安全说明")
    parser.add_argument("--skip-s3", action="store_true", help="跳过对象存储上传")
    parser.add_argument("--skip-db", action="store_true", help="跳过数据库注册")
    parser.add_argument("--batch-size", type=int, default=MIGRATION_BATCH_SIZE_DEFAULT)
    parser.add_argument("--migration-id", type=str, default="")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)

    if args.rollback:
        print("BLOCKED: 禁止无迁移批次作用域的自动回滚。")
        print("必须使用已签迁移批次清单，在隔离环境验证逐对象/逐记录补偿计划后执行。")
        return 2

    execution_mode = (
        "DRY_RUN"
        if args.dry_run
        else "PARTIAL"
        if args.skip_s3 or args.skip_db
        else "EXECUTE"
    )
    if args.batch_size <= 0:
        print("错误: --batch-size 必须为正整数。")
        return 1
    if (args.skip_s3 or args.skip_db) and not args.dry_run:
        print("BLOCKED: 禁止仅写入数据库或对象存储的非干跑迁移；必须保持单批次原子编排。")
        return 2
    if execution_mode == "EXECUTE" and not args.migration_id.strip():
        print("BLOCKED: 真实迁移必须提供不可变 --migration-id。")
        return 2

    phases: Dict[str, MigrationReport] = {}
    baseline_manifest = CONTROLLED_OUTPUT / "baseline-180" / "manifest.csv"
    retrain_manifest = CONTROLLED_OUTPUT / "retrain-172" / "manifest.csv"
    baseline_checksums = CONTROLLED_OUTPUT / "baseline-180" / "checksums.sha256"
    retrain_checksums = CONTROLLED_OUTPUT / "retrain-172" / "checksums.sha256"

    if not baseline_manifest.exists():
        print("错误: P6-01 baseline-180 manifest 不存在，请先运行 migrate.py")
        return 1

    try:
        source_summary = load_summary()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"错误: 无法读取 P6-01 受控输出摘要: {type(exc).__name__}")
        return 1
    source_approved, source_blockers = source_is_approved(source_summary)
    if execution_mode == "EXECUTE" and not source_approved:
        print("BLOCKED: P6-01 受控源未获准用于生产迁移。")
        for blocker in source_blockers:
            print(f"  - {blocker}")
        return 2

    records = load_manifest_csv(baseline_manifest)
    retrain_records = load_manifest_csv(retrain_manifest) if retrain_manifest.exists() else []
    all_checksums = {**load_checksums(baseline_checksums), **load_checksums(retrain_checksums)}

    # Phase 1: 源完整性验证
    print("Phase 1: 源完整性验证")
    integrity = verify_source_integrity(records, all_checksums)
    print(f"  源文件: {integrity['passed']}/{integrity['total']} 通过, {integrity['failed']} 失败")
    phases["verify_source"] = MigrationReport(
        phase="verify_source",
        status="PASSED" if integrity["failed"] == 0 else "FAILED",
        details={"passed": integrity["passed"], "total": integrity["total"], "failed": integrity["failed"]},
        errors=[f["reason"] for f in integrity["failures"]],
    )

    if integrity["failed"] > 0:
        print("  错误: 源完整性验证失败")
        for f in integrity["failures"][:10]:
            print(f"    {f['sample_id']}: {f['reason']}")
        if len(integrity["failures"]) > 10:
            print(f"    ... 还有 {len(integrity['failures']) - 10} 项")

    # Phase 2: 对象存储上传
    s3_phase_errors: List[str] = []
    upload_result = {"uploaded": 0, "failed": 0}

    if not args.skip_s3:
        print("\nPhase 2: 对象存储迁移")
        try:
            s3 = S3Client(
                endpoint=env_required("S3_ENDPOINT"),
                access_key=env_required("S3_ACCESS_KEY"),
                secret_key=env_required("S3_SECRET_KEY"),
                bucket=env_required("S3_BUCKET"),
            )
            upload_result = migrate_objects_to_s3(s3, records, args.dry_run)
            print(f"  已上传: {upload_result['uploaded']}, 失败: {upload_result['failed']}")
            if upload_result["total_bytes"] > 0:
                print(f"  总大小: {upload_result['total_bytes']:,} 字节 ({upload_result['total_bytes'] / 1024 / 1024:.1f} MB)")
            s3_phase_errors = [f["error"] for f in upload_result.get("failures", [])]
        except SystemExit:
            message = "S3 环境变量未配置"
            print(f"  BLOCKED: {message}")
            s3_phase_errors.append(message)
        except Exception as e:
            s3_phase_errors.append(str(e))
    else:
        print("\nPhase 2: 对象存储迁移（已跳过）")
        upload_result = call_s3_dry(records)

    if args.skip_s3:
        s3_status = "SKIPPED"
    elif args.dry_run and not s3_phase_errors:
        s3_status = "DRY_RUN"
    elif s3_phase_errors:
        s3_status = "BLOCKED" if any("环境变量未配置" in item for item in s3_phase_errors) else "FAILED"
    else:
        expected_objects = len(records) * 2
        s3_status = "PASSED" if upload_result.get("uploaded") == expected_objects else "FAILED"
    phases["migrate_objects"] = MigrationReport(
        phase="migrate_objects",
        status=s3_status,
        details={"uploaded": upload_result.get("uploaded", 0), "failed": upload_result.get("failed", 0)},
        errors=s3_phase_errors,
    )

    # Phase 3: 数据库注册
    db_phase_errors: List[str] = []
    db_counts = {"image_objects": 0, "capture_events": 0}

    if not args.skip_db:
        print("\nPhase 3: 数据库引用注册")
        try:
            db = DatabaseClient(
                db_url=env_required("DB_URL"),
                db_user=env_required("DB_USER"),
                db_password=env_required("DB_PASSWORD"),
            )
            if args.dry_run:
                db.set_dry_run(True)
                print("  [DRY-RUN] 不实际写入数据库")
            db_counts = register_database_references(db, None, records, retrain_records, args.dry_run)
            print(f"  已注册 image_objects: {db_counts.get('image_objects', 0)}")
            print(f"  已注册 capture_events: {db_counts.get('capture_events', 0)}")
        except SystemExit:
            message = "DB 环境变量未配置"
            print(f"  BLOCKED: {message}")
            db_phase_errors.append(message)
        except Exception as e:
            db_phase_errors.append(str(e))
    else:
        print("\nPhase 3: 数据库注册（已跳过）")

    if args.skip_db:
        db_status = "SKIPPED"
    elif args.dry_run and not db_phase_errors:
        db_status = "DRY_RUN"
    elif db_phase_errors:
        db_status = "BLOCKED" if any("环境变量未配置" in item for item in db_phase_errors) else "FAILED"
    else:
        db_status = "PASSED"
    phases["register_database"] = MigrationReport(
        phase="register_database",
        status=db_status,
        details=db_counts,
        errors=db_phase_errors,
    )

    # Phase 4: 验证
    print("\nPhase 4: 迁移验证")
    try:
        db_url = env_optional("DB_URL", "")
        if db_url:
            db = DatabaseClient(
                db_url=db_url,
                db_user=env_optional("DB_USER", ""),
                db_password=env_optional("DB_PASSWORD", ""),
            )
            if args.dry_run:
                db.set_dry_run(True)
            counts = verify_migration_counts(len(records), db, args.dry_run)
            print(f"  image_object: {counts['image_object_count']}/{counts.get('expected_images', '?')}")
            print(f"  capture_event: {counts['capture_event_count']}/{counts.get('expected_captures', '?')}")
            print(f"  dataset_version: {counts['dataset_version_count']}/{counts.get('expected_dataset_versions', '?')}")
            print(f"  model_version: {counts['model_version_count']}/{counts.get('expected_model_versions', '?')}")
            if args.dry_run:
                verify_status = "DRY_RUN"
                verify_errors: List[str] = []
            else:
                verify_status = "PASSED" if counts.get("all_match", False) else "FAILED"
                verify_errors = [] if counts.get("all_match", False) else ["count mismatch"]
            phases["verify_counts"] = MigrationReport(
                phase="verify_counts",
                status=verify_status,
                details=counts,
                errors=verify_errors,
            )
        else:
            phases["verify_counts"] = MigrationReport(
                phase="verify_counts",
                status="BLOCKED",
                details={"reason": "DB_URL not configured"},
                errors=[],
            )
    except Exception as e:
        phases["verify_counts"] = MigrationReport(
            phase="verify_counts",
            status="FAILED",
            details={},
            errors=[str(e)],
        )

    # 生成报告；干跑、部分运行、阻塞和跳过永远不能形成 COMPLETE。
    summary = summarize_phases(phases, execution_mode=execution_mode)

    report = generate_report(
        phases,
        summary,
        source_summary=source_summary,
        migration_id=args.migration_id,
        execution_mode=execution_mode,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "migration-report.json"
    if report_path.exists():
        print(f"错误: 拒绝覆盖已有迁移报告: {report_path}")
        return 1
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(f"\n迁移报告: {report_path}")
    if summary["overall_status"] == "COMPLETE":
        return 0
    if summary["overall_status"] == "BLOCKED":
        return 2
    return 1


def call_s3_dry(records: List[SourceRecord]) -> Dict[str, Any]:
    count = 0
    total_bytes = 0
    for rec in records:
        if rec.errors == 0:
            count += 2
            total_bytes += rec.image_size_bytes + rec.mask_size_bytes
    return {"uploaded": count, "failed": 0, "total_bytes": total_bytes, "dry_run": True}


if __name__ == "__main__":
    sys.exit(main())
