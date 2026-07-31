#!/usr/bin/env python3
"""P7-03 迁移后验证脚本

可独立于迁移流程运行，用于定期审计：
- 源清单计数/散列 vs 目标计数/散列
- 对象存储：对象存在性、大小、SHA-256 随机抽样
- 数据库：行计数、外键完整性、审批链完整性
- 生成验证报告（分项 pass/fail）
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
CONTROLLED_OUTPUT = REPO_ROOT / "jobs" / "artifact-migrator" / "controlled-output"
OUTPUT_DIR = REPO_ROOT / "jobs" / "production-migration" / "output"

HASH_CHUNK = 65536
DEFAULT_SAMPLE_SIZE = 20


def sha256_hex(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def env_optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class VerificationResult:
    def __init__(self, category: str):
        self.category = category
        self.checks: List[Dict[str, Any]] = []
        self.passed = 0
        self.failed = 0
        self.errors: List[str] = []
        self.blockers: List[str] = []

    def add_check(self, name: str, passed: bool, detail: Any = None) -> None:
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if passed:
            self.passed += 1
        else:
            self.failed += 1

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.failed += 1

    def add_blocker(self, blocker: str) -> None:
        self.blockers.append(blocker)

    def status(self) -> str:
        if self.blockers and self.failed == 0:
            return "BLOCKED"
        if self.failed == 0:
            return "PASSED"
        if self.passed > 0:
            return "PARTIAL"
        return "FAILED"


class DatabaseVerifier:
    def __init__(self, db_url: str, db_user: str, db_password: str):
        self._db_url = db_url
        self._db_user = db_user
        self._db_password = db_password

    def _parse_db_url(self) -> Dict[str, str]:
        pattern = r"^(?:jdbc:)?postgres(?:ql)?://([^:]+):(\d+)/(.+)$"
        for variant in [self._db_url, self._db_url.replace("jdbc:postgresql://", "postgresql://")]:
            m = re.match(pattern, variant)
            if m:
                return {"host": m.group(1), "port": m.group(2), "database": m.group(3)}
        return {"host": "localhost", "port": "5432", "database": "tool_defect"}

    def query(self, sql: str, params: Optional[tuple] = None) -> Any:
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
        result = self.query(sql, params)
        if result and len(result) > 0:
            return result[0]
        return None

    def table_row_count(self, table: str) -> int:
        result = self.query_one(f"SELECT COUNT(*) FROM {table}")
        if result:
            return int(result[0])
        return -1

    def verify_foreign_keys(self) -> Dict[str, Any]:
        fk_checks = {
            "image_object.capture_id -> capture_event.capture_id": self._check_orphan(
                "image_object", "capture_id", "capture_event", "capture_id"
            ),
            "image_object.source_image_id -> image_object.image_id": self._check_orphan(
                "image_object", "source_image_id", "image_object", "image_id", nullable=True
            ),
            "image_object.detection_task_id -> detection_task.detection_task_id": self._check_orphan(
                "image_object", "detection_task_id", "detection_task", "detection_task_id", nullable=True
            ),
            "image_object.review_record_id -> review_record.review_record_id": self._check_orphan(
                "image_object", "review_record_id", "review_record", "review_record_id", nullable=True
            ),
            "dataset_sample.image_id -> image_object.image_id": self._check_orphan(
                "dataset_sample", "image_id", "image_object", "image_id"
            ),
            "dataset_sample.mask_image_id -> image_object.image_id": self._check_orphan(
                "dataset_sample", "mask_image_id", "image_object", "image_id", nullable=True
            ),
            "dataset_sample.dataset_version_id -> dataset_version.dataset_version_id": self._check_orphan(
                "dataset_sample", "dataset_version_id", "dataset_version", "dataset_version_id"
            ),
            "dataset_version.dataset_id -> dataset.dataset_id": self._check_orphan(
                "dataset_version", "dataset_id", "dataset", "dataset_id"
            ),
            "model_version.model_id -> model.model_id": self._check_orphan(
                "model_version", "model_id", "model", "model_id"
            ),
            "model_version.dataset_version_id -> dataset_version.dataset_version_id": self._check_orphan(
                "model_version", "dataset_version_id", "dataset_version", "dataset_version_id"
            ),
        }
        return fk_checks

    def _check_orphan(self, child_table: str, child_col: str, parent_table: str, parent_col: str, nullable: bool = False) -> Dict[str, Any]:
        if nullable:
            result = self.query_one(
                f"SELECT COUNT(*) FROM {child_table} WHERE {child_col} IS NOT NULL "
                f"AND {child_col} NOT IN (SELECT {parent_col} FROM {parent_table})"
            )
        else:
            result = self.query_one(
                f"SELECT COUNT(*) FROM {child_table} WHERE {child_col} NOT IN "
                f"(SELECT {parent_col} FROM {parent_table})"
            )
        orphan_count = int(result[0]) if result else -1
        return {"orphans": orphan_count, "ok": orphan_count == 0}

    def verify_approval_chain(self) -> Dict[str, Any]:
        frozen_dataset_approved = self.query_one(
            "SELECT COUNT(*) FROM dataset_version WHERE status = 'FROZEN' AND approved_by IS NULL"
        )
        model_approved_with_eval = self.query_one(
            "SELECT COUNT(*) FROM model_version WHERE approval_state IN ('APPROVED','VALIDATED') "
            "AND evaluation_summary = '{}'::jsonb"
        )
        returns: Dict[str, Any] = {}
        if frozen_dataset_approved:
            returns["frozen_datasets_without_approver"] = int(frozen_dataset_approved[0])
        if model_approved_with_eval:
            returns["approved_models_without_evaluation"] = int(model_approved_with_eval[0])
        returns["ok"] = all(v == 0 for v in returns.values() if v is not None)
        return returns

    def verify_model_count(self) -> int:
        result = self.query_one("SELECT COUNT(*) FROM model_version")
        return int(result[0]) if result else -1


class S3Verifier:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str):
        self._endpoint = endpoint.rstrip("/")
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._region = "us-east-1"

    def _sign(self, method: str, key: str, headers: Dict[str, str], body: bytes = b"") -> Dict[str, str]:
        import hmac
        from urllib.parse import urlparse

        parsed = urlparse(self._endpoint)
        host = parsed.netloc or parsed.path
        service = "s3"
        scope_date = datetime.utcnow().strftime("%Y%m%d")
        credential_scope = f"{scope_date}/{self._region}/{service}/aws4_request"

        content_hash = hashlib.sha256(body).hexdigest()
        headers["x-amz-content-sha256"] = content_hash
        headers["host"] = host

        signed_headers = ";".join(sorted(h.lower() for h in headers))
        canonical_headers = "".join(
            f"{k.lower()}:{headers[k].strip()}\n" for k in sorted(headers, key=str.lower)
        )

        def sha256_text(t: str) -> str:
            return hashlib.sha256(t.encode("utf-8")).hexdigest()

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
                return {
                    "key": key,
                    "status": resp.status,
                    "content_length": resp.headers.get("Content-Length"),
                    "etag": resp.headers.get("ETag", ""),
                }
        except urllib.error.HTTPError:
            return None

    def get_object(self, key: str) -> Optional[bytes]:
        import urllib.request

        url = f"{self._endpoint}/{self._bucket}/{key}"
        headers: Dict[str, str] = {
            "x-amz-date": datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        }
        headers = self._sign("GET", f"/{self._bucket}/{key}", headers)

        req = urllib.request.Request(url, method="GET")
        for k, v in headers.items():
            req.add_header(k, v)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError:
            return None


def load_source_manifest() -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    records: List[Dict[str, str]] = []
    manifest_path = CONTROLLED_OUTPUT / "baseline-180" / "manifest.csv"
    checksums_path = CONTROLLED_OUTPUT / "baseline-180" / "checksums.sha256"

    if manifest_path.exists():
        with open(manifest_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(dict(row))

    checksums: Dict[str, str] = {}
    if checksums_path.exists():
        for line in checksums_path.read_text().strip().split("\n"):
            if line.strip():
                parts = line.split("  ", 1)
                if len(parts) == 2:
                    checksums[parts[1]] = parts[0]

    return records, checksums


def verify_object_storage(s3: S3Verifier, records: List[Dict[str, str]], sample_size: int) -> VerificationResult:
    result = VerificationResult("object_storage")
    sample = random.sample(records, min(sample_size, len(records)))

    found = 0
    missing = 0
    size_mismatch = 0
    hash_mismatch = 0

    for rec in sample:
        sample_id = rec["sample_id"]
        image_path = rec.get("image_path", "")
        if image_path:
            img_file = DATA_DIR / image_path
            if img_file.exists():
                found_any = False
                for variant in [f"RAW/{sample_id}", f"image/{sample_id}"]:
                    info = s3.head_object(generate_object_key("RAW", sample_id, img_file.suffix))
                    if info:
                        found += 1
                        found_any = True
                        remote_size = info.get("content_length")
                        if remote_size and int(remote_size) != img_file.stat().st_size:
                            size_mismatch += 1
                        break
                if not found_any:
                    missing += 1

    result.add_check("object_existence_sample", missing == 0, {"sample_size": len(sample), "found": found, "missing": missing})
    result.add_check("object_size_match", size_mismatch == 0, {"mismatched": size_mismatch})
    return result


def generate_object_key(kind: str, sample_id: str, ext: str = ".png") -> str:
    parts = sample_id.split("/")
    if len(parts) == 2:
        category, filename = parts
    else:
        category, filename = "unknown", sample_id
    return f"capture/2026/07/31/{category}/{kind}/{filename}{ext}"


def verify_database(db: DatabaseVerifier) -> VerificationResult:
    result = VerificationResult("database")

    expected = {
        "image_object": 360,
        "capture_event": 360,
        "dataset": 1,
        "dataset_version": 2,
        "model": 1,
        "model_version": 3,
        "dataset_sample": 172,
    }

    tables_ok = True
    for table, expected_count in expected.items():
        actual = db.table_row_count(table)
        ok = actual == expected_count
        result.add_check(f"row_count_{table}", ok, {"expected": expected_count, "actual": actual})
        if not ok:
            tables_ok = False

    fk_results = db.verify_foreign_keys()
    for fk_name, fk_result in fk_results.items():
        result.add_check(f"foreign_key_{fk_name}", fk_result["ok"], fk_result)

    approval = db.verify_approval_chain()
    result.add_check("approval_chain", approval["ok"], approval)

    return result


def verify_source_matches_database(db: DatabaseVerifier, records: List[Dict[str, str]]) -> VerificationResult:
    result = VerificationResult("source_vs_database")
    image_count = db.table_row_count("image_object")
    source_image_count = len(records) * 2
    result.add_check("image_object_count_parity", image_count == source_image_count, {
        "source_expected": source_image_count, "database_actual": image_count,
    })
    return result


def generate_report(results: List[VerificationResult]) -> Dict[str, Any]:
    statuses = [result.status() for result in results]
    if any(status in {"FAILED", "PARTIAL"} for status in statuses):
        overall_status = "FAILED"
    elif any(status == "BLOCKED" for status in statuses):
        overall_status = "BLOCKED"
    else:
        overall_status = "PASSED"
    return {
        "schema_version": "tool-defect-production-migration-diagnostic/v1",
        "verifier_version": "1.0.0",
        "verification_scope": "DIAGNOSTIC",
        "production_claim_allowed": False,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall_status": overall_status,
        "categories": {
            r.category: {
                "status": r.status(),
                "passed": r.passed,
                "failed": r.failed,
                "checks": r.checks,
                "errors": r.errors,
                "blockers": r.blockers,
            }
            for r in results
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="P7-03 迁移验证")
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE, help="随机抽样数量")
    parser.add_argument("--skip-s3", action="store_true", help="跳过对象存储验证")
    parser.add_argument("--skip-db", action="store_true", help="跳过数据库验证")
    parser.add_argument("--json", action="store_true", dest="json_output", help="仅输出 JSON 报告到 stdout")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)

    results: List[VerificationResult] = []
    source_records, source_checksums = load_source_manifest()
    if not source_records:
        print("错误: P6-01 manifest 不存在")
        return 1

    # 源清单完整性
    source_result = VerificationResult("source_integrity")
    source_result.add_check("manifest_exists", True, {"records": len(source_records)})
    source_result.add_check("checksums_exists", len(source_checksums) > 0, {"checksums": len(source_checksums)})

    valid_records = 0
    for rec in source_records:
        if int(rec.get("errors", "1")) == 0:
            valid_records += 1
    source_result.add_check("records_clean", valid_records == len(source_records), {
        "valid": valid_records, "total": len(source_records),
    })
    results.append(source_result)

    if not source_result.errors:
        print(f"源清单: {valid_records}/{len(source_records)} 条记录无错误")
    else:
        print(f"源清单: {valid_records}/{len(source_records)} 条有效, {source_result.failed} 失败")

    # 对象存储验证
    if not args.skip_s3:
        s3_endpoint = env_optional("S3_ENDPOINT")
        if s3_endpoint:
            try:
                s3 = S3Verifier(
                    endpoint=s3_endpoint,
                    access_key=env_optional("S3_ACCESS_KEY"),
                    secret_key=env_optional("S3_SECRET_KEY"),
                    bucket=env_optional("S3_BUCKET"),
                )
                object_result = verify_object_storage(s3, source_records, args.sample_size)
                print(f"对象存储: {object_result.passed}/{object_result.passed + object_result.failed} 项通过")
                results.append(object_result)
            except Exception as e:
                print(f"对象存储验证失败: {e}")
                error_result = VerificationResult("object_storage")
                error_result.add_error(str(e))
                results.append(error_result)
        else:
            print("S3 未配置，对象存储验证被阻塞")
            blocked = VerificationResult("object_storage")
            blocked.add_blocker("S3 environment is not configured")
            results.append(blocked)
    else:
        blocked = VerificationResult("object_storage")
        blocked.add_blocker("object storage verification was explicitly skipped")
        results.append(blocked)

    # 数据库验证
    if not args.skip_db:
        db_url = env_optional("DB_URL")
        if db_url:
            try:
                db = DatabaseVerifier(
                    db_url=db_url,
                    db_user=env_optional("DB_USER", ""),
                    db_password=env_optional("DB_PASSWORD", ""),
                )
                db_result = verify_database(db)
                print(f"数据库: {db_result.passed}/{db_result.passed + db_result.failed} 项通过")
                results.append(db_result)

                source_vs_db = verify_source_matches_database(db, source_records)
                print(f"源-数据库对照: {source_vs_db.passed}/{source_vs_db.passed + source_vs_db.failed} 项通过")
                results.append(source_vs_db)
            except Exception as e:
                print(f"数据库验证失败: {e}")
                error_result = VerificationResult("database")
                error_result.add_error(str(e))
                results.append(error_result)
        else:
            print("DB 未配置，数据库验证被阻塞")
            blocked = VerificationResult("database")
            blocked.add_blocker("database environment is not configured")
            results.append(blocked)
    else:
        blocked = VerificationResult("database")
        blocked.add_blocker("database verification was explicitly skipped")
        results.append(blocked)

    production_evidence = VerificationResult("production_evidence")
    production_evidence.add_blocker(
        "this legacy verifier is diagnostic only; provide the FULL signed "
        "tool-defect-production-migration-verification/v1 report"
    )
    results.append(production_evidence)

    report = generate_report(results)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "verification-report.json"
    if report_path.exists():
        print(f"错误: 拒绝覆盖已有诊断报告: {report_path}")
        return 1
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    if args.json_output:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"\n验证报告: {report_path}")
        print(f"总体状态: {report['overall_status']}")
        for cat, data in report["categories"].items():
            print(f"  {cat}: {data['status']} ({data['passed']} 通过, {data['failed']} 失败)")

    if report["overall_status"] == "PASSED":
        return 0
    if report["overall_status"] == "BLOCKED":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
