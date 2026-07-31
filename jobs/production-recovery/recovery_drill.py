#!/usr/bin/env python3
"""P7-03 生产恢复演练编排器

扩展 P5-05 联合恢复到生产规模数据，验证：
1. 备份快照存在性与散列有效性
2. 隔离环境恢复
3. 采集记录、检测结果、复核记录、模型记录的业务验证
4. 对象存储中图片/掩码/数据集/模型的对象验证
5. 模型加载与推断功能验证
6. 审批链完整性验证

退出码: 0 = 全部验证通过, 非零 = 发现失败
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "jobs" / "production-recovery" / "output"

HASH_CHUNK = 65536

REQUIRED_COMPONENTS = [
    "business_records",
    "object_storage",
    "current_model",
    "dataset_manifest",
    "approval_evidence",
    "human_review_chain",
]

REQUIRED_SCENARIOS = [
    "snapshot_backup",
    "isolated_restore",
    "business_records",
    "object_storage",
    "model_functionality",
    "approval_chain",
]

ALLOWED_SOURCE_TYPES = {"REAL_PRODUCTION"}
REQUIRED_ENVIRONMENT = "ISOLATED_PRODUCTION_EQUIVALENT"


def sha256_hex(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def env_optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class RecoveryDrillOrchestrator:
    def __init__(
        self,
        drill_id: str,
        *,
        source_type: str = "UNKNOWN",
        environment: str = "UNKNOWN",
        executor_id: str = "",
        rpo_target_seconds: float = 0,
        rto_target_seconds: float = 0,
        migration_verification_path: str = "",
        raw_log_path: str = "",
        sign_off: Optional[Dict[str, Any]] = None,
    ):
        self.drill_id = drill_id
        self.source_type = source_type
        self.environment = environment
        self.executor_id = executor_id
        self.rpo_target_seconds = rpo_target_seconds
        self.rpo_actual_seconds: Optional[float] = None
        self.rto_target_seconds = rto_target_seconds
        self.migration_verification_path = migration_verification_path
        self.raw_log_path = raw_log_path
        self.sign_off = sign_off or {}
        self.started_at = datetime.now(timezone.utc)
        self.scenarios: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []

    def _check_result(self, scenario: str, passed: bool, detail: Any = None) -> Dict[str, Any]:
        result = {
            "scenario": scenario,
            "passed": passed,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if not passed:
            self.errors.append(result)
        self.scenarios.append(result)
        return result

    def verify_snapshot_backup(self, snapshot_path: Optional[str] = None) -> Dict[str, Any]:
        """Phase 1: 备份快照存在性与散列验证"""
        if not snapshot_path:
            return self._check_result("snapshot_backup", False, "snapshot_path not provided")

        snap = Path(snapshot_path)
        if not snap.exists():
            return self._check_result("snapshot_backup", False, f"snapshot not found: {snap}")

        manifest_file = snap / "manifest.json"
        if not manifest_file.exists():
            return self._check_result("snapshot_backup", False, "manifest.json missing")

        try:
            manifest = json.loads(manifest_file.read_text())
        except json.JSONDecodeError as e:
            return self._check_result("snapshot_backup", False, f"manifest.json parse error: {e}")

        if manifest.get("schema_version") != "tool-defect-production-snapshot/v1":
            return self._check_result("snapshot_backup", False, "snapshot schema invalid")
        if manifest.get("source_type") != "REAL_PRODUCTION":
            return self._check_result("snapshot_backup", False, "snapshot source is not real production")
        if manifest.get("production_claim_allowed") is not True:
            return self._check_result("snapshot_backup", False, "snapshot production claim not allowed")
        if not isinstance(manifest.get("snapshot_id"), str) or not manifest["snapshot_id"].strip():
            return self._check_result("snapshot_backup", False, "snapshot_id missing")
        created_at = manifest.get("created_at")
        if not isinstance(created_at, str):
            return self._check_result("snapshot_backup", False, "snapshot created_at missing")
        try:
            snapshot_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return self._check_result("snapshot_backup", False, "snapshot created_at invalid")
        self.rpo_actual_seconds = (self.started_at - snapshot_created_at).total_seconds()
        if self.rpo_actual_seconds < 0:
            return self._check_result("snapshot_backup", False, "snapshot created_at is in the future")

        components = manifest.get("components")
        if not isinstance(components, dict):
            return self._check_result("snapshot_backup", False, "components must be an object")
        missing = [c for c in REQUIRED_COMPONENTS if c not in components]
        if missing:
            return self._check_result("snapshot_backup", False, f"missing components: {missing}")

        hash_errors: List[str] = []
        verified_files = 0
        resolved_snapshot = snap.resolve()
        for component in REQUIRED_COMPONENTS:
            descriptor = components.get(component)
            if not isinstance(descriptor, dict):
                hash_errors.append(f"{component}: descriptor must be an object")
                continue
            relative_path = descriptor.get("path")
            expected_hash = descriptor.get("sha256")
            if not isinstance(relative_path, str) or not relative_path.strip():
                hash_errors.append(f"{component}: path missing")
                continue
            if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
                hash_errors.append(f"{component}: sha256 invalid")
                continue
            try:
                fpath = (snap / relative_path).resolve(strict=True)
                fpath.relative_to(resolved_snapshot)
            except (OSError, RuntimeError, ValueError):
                hash_errors.append(f"{component}: file missing or outside snapshot")
                continue
            if not fpath.is_file() or fpath.is_symlink():
                hash_errors.append(f"{component}: component is not a regular file")
                continue
            actual = sha256_hex(fpath)
            if actual != expected_hash:
                hash_errors.append(
                    f"{component}: expected {expected_hash[:16]}... got {actual[:16]}..."
                )
                continue
            verified_files += 1

        if hash_errors:
            return self._check_result("snapshot_backup", False, {
                "component_count": len(components),
                "verified_files": verified_files,
                "hash_errors": hash_errors,
            })

        return self._check_result("snapshot_backup", True, {
            "snapshot_id": manifest["snapshot_id"],
            "snapshot_created_at": created_at,
            "rpo_actual_seconds": self.rpo_actual_seconds,
            "manifest_sha256": sha256_hex(manifest_file),
            "component_count": len(components),
            "verified_files": verified_files,
            "all_components_present": True,
            "all_hashes_valid": True,
        })

    def verify_isolated_restore(self, source_path: str, target_path: str) -> Dict[str, Any]:
        """Phase 2: 隔离环境恢复"""
        if not source_path.strip():
            return self._check_result("isolated_restore", False, "source path not provided")
        source = Path(source_path)
        target = Path(target_path)

        if not source.is_dir():
            return self._check_result("isolated_restore", False, f"source not found: {source}")

        if target.exists() and any(target.iterdir()):
            return self._check_result("isolated_restore", False, "target directory is not empty")

        target.mkdir(parents=True, exist_ok=True)

        if source.resolve() == target.resolve() or source.resolve() in target.resolve().parents:
            return self._check_result("isolated_restore", False, "target must be isolated from source")

        files_restored = 0
        verify_errors: List[str] = []
        source_files = sorted(item for item in source.rglob("*") if item.is_file())
        if not source_files:
            return self._check_result("isolated_restore", False, "snapshot contains no files")
        for item in source_files:
            if item.is_symlink():
                verify_errors.append(f"{item.relative_to(source)}: symbolic link is not allowed")
                continue
            relative = item.relative_to(source)
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            actual = sha256_hex(dest)
            source_hash = sha256_hex(item)
            if actual != source_hash:
                verify_errors.append(f"{relative}: hash mismatch after copy")
            else:
                files_restored += 1

        if verify_errors:
            return self._check_result("isolated_restore", False, {"files_restored": files_restored, "errors": verify_errors})

        return self._check_result("isolated_restore", True, {"files_restored": files_restored, "target": str(target)})

    def verify_business_records(self, db_url: Optional[str] = None) -> Dict[str, Any]:
        """Phase 3: 业务记录验证"""
        if not db_url:
            return self._check_result("business_records", False, "no database URL configured")

        tables = [
            "capture_event",
            "detection_result",
            "review_task",
            "review_record",
            "disposition_record",
            "model_version",
            "dataset_version",
        ]
        try:
            import psycopg2
        except ImportError as exc:
            return self._check_result("business_records", False, f"database driver missing: {type(exc).__name__}")

        dsn = db_url.removeprefix("jdbc:")
        connect_options: Dict[str, Any] = {"connect_timeout": 10}
        if env_optional("DB_USER"):
            connect_options["user"] = env_optional("DB_USER")
        if env_optional("DB_PASSWORD"):
            connect_options["password"] = env_optional("DB_PASSWORD")
        try:
            connection = psycopg2.connect(dsn, **connect_options)
            connection.set_session(readonly=True, autocommit=True)
            with connection.cursor() as cursor:
                row_counts: Dict[str, int] = {}
                for table in tables:
                    cursor.execute("SELECT to_regclass(%s)", (f"public.{table}",))
                    exists = cursor.fetchone()
                    if not exists or exists[0] is None:
                        row_counts[table] = -1
                        continue
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    row_counts[table] = int(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT version FROM flyway_schema_history "
                    "WHERE success = true ORDER BY installed_rank DESC LIMIT 1"
                )
                flyway_row = cursor.fetchone()
        except Exception as exc:
            return self._check_result(
                "business_records",
                False,
                {"error": type(exc).__name__, "tables_checked": tables},
            )
        finally:
            if "connection" in locals():
                connection.close()

        latest_version = str(flyway_row[0]) if flyway_row else ""
        match = re.match(r"^(\d+)", latest_version)
        schema_current = bool(match and int(match.group(1)) >= 11)
        all_present = all(count > 0 for count in row_counts.values())
        return self._check_result("business_records", all_present and schema_current, {
            "tables_checked": tables,
            "row_counts": row_counts,
            "latest_flyway_version": latest_version,
            "required_flyway_version": 11,
        })

    def verify_object_storage(self, verification_report_path: Optional[str] = None) -> Dict[str, Any]:
        """Phase 4: 对象存储验证"""
        if not verification_report_path:
            return self._check_result("object_storage", False, "migration verification report not provided")
        report_path = Path(verification_report_path)
        if not report_path.is_file():
            return self._check_result("object_storage", False, "migration verification report missing")
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return self._check_result("object_storage", False, f"verification report invalid: {type(exc).__name__}")
        categories = report.get("categories")
        object_result = categories.get("object_storage") if isinstance(categories, dict) else None
        passed = (
            report.get("schema_version") == "tool-defect-production-migration-verification/v1"
            and report.get("overall_status") == "PASS"
            and report.get("source_type") == "REAL_PRODUCTION"
            and report.get("verification_scope") == "FULL"
            and isinstance(object_result, dict)
            and object_result.get("status") == "PASS"
            and isinstance(object_result.get("expected_objects"), int)
            and object_result.get("expected_objects", 0) > 0
            and object_result.get("verified_objects") == object_result.get("expected_objects")
            and object_result.get("missing_objects") == 0
            and object_result.get("hash_mismatches") == 0
            and object_result.get("expected_bytes") == object_result.get("verified_bytes")
        )
        return self._check_result("object_storage", passed, {
            "verification_report_sha256": sha256_hex(report_path),
            "migration_id": report.get("migration_id"),
            "object_storage": object_result,
        })

    def verify_model_functionality(self, smoke_evidence_path: Optional[str] = None) -> Dict[str, Any]:
        """Phase 5: 模型功能验证"""
        if not smoke_evidence_path:
            return self._check_result("model_functionality", False, "model smoke evidence not provided")
        smoke_path = Path(smoke_evidence_path)
        if not smoke_path.is_file():
            return self._check_result("model_functionality", False, "model smoke evidence missing")
        sys.path.insert(0, str(REPO_ROOT))
        try:
            from tools.p7.preflight import validate_smoke_evidence

            validation = validate_smoke_evidence(repo_root=REPO_ROOT, evidence_path=smoke_path)
        except Exception as exc:
            return self._check_result("model_functionality", False, f"model smoke validator failed: {type(exc).__name__}")
        return self._check_result("model_functionality", validation.status == "PASS", {
            "validation_status": validation.status,
            "blockers": validation.blockers,
            "errors": validation.errors,
            "evidence_sha256": sha256_hex(smoke_path),
        })

    def verify_approval_chain(self, db_url: Optional[str] = None) -> Dict[str, Any]:
        """Phase 6: 审批链验证"""
        db_url = db_url or env_optional("DB_URL")
        if not db_url:
            return self._check_result("approval_chain", False, "no database URL configured")
        try:
            import psycopg2
        except ImportError as exc:
            return self._check_result("approval_chain", False, f"database driver missing: {type(exc).__name__}")

        dsn = db_url.removeprefix("jdbc:")
        connect_options: Dict[str, Any] = {"connect_timeout": 10}
        if env_optional("DB_USER"):
            connect_options["user"] = env_optional("DB_USER")
        if env_optional("DB_PASSWORD"):
            connect_options["password"] = env_optional("DB_PASSWORD")
        queries = {
            "frozen_datasets_without_approver": (
                "SELECT COUNT(*) FROM dataset_version "
                "WHERE status = 'FROZEN' AND approved_by IS NULL"
            ),
            "released_models_without_full_approval": (
                "SELECT COUNT(*) FROM model_version WHERE approval_state = 'APPROVED' "
                "AND (validated_by IS NULL OR approved_by IS NULL "
                "OR validated_by = approved_by OR evaluation_report_sha256 IS NULL "
                "OR threshold_gate_sha256 IS NULL)"
            ),
            "released_models_without_two_records": (
                "SELECT COUNT(*) FROM model_version mv WHERE mv.approval_state = 'APPROVED' "
                "AND NOT EXISTS (SELECT 1 FROM model_version_approval va "
                "WHERE va.model_version_id = mv.model_version_id AND va.stage = 'VALIDATION' "
                "AND va.decision = 'APPROVE') "
                "OR mv.approval_state = 'APPROVED' AND NOT EXISTS "
                "(SELECT 1 FROM model_version_approval ra WHERE ra.model_version_id = mv.model_version_id "
                "AND ra.stage = 'RELEASE' AND ra.decision = 'APPROVE')"
            ),
            "review_records_without_reason": (
                "SELECT COUNT(*) FROM review_record WHERE length(trim(reason_code)) = 0"
            ),
        }
        try:
            connection = psycopg2.connect(dsn, **connect_options)
            connection.set_session(readonly=True, autocommit=True)
            counts: Dict[str, int] = {}
            with connection.cursor() as cursor:
                for name, query in queries.items():
                    cursor.execute(query)
                    counts[name] = int(cursor.fetchone()[0])
        except Exception as exc:
            return self._check_result("approval_chain", False, {"error": type(exc).__name__})
        finally:
            if "connection" in locals():
                connection.close()

        return self._check_result("approval_chain", all(value == 0 for value in counts.values()), counts)

    def generate_report(self) -> Dict[str, Any]:
        total = len(self.scenarios)
        passed = sum(1 for s in self.scenarios if s["passed"])
        failed = total - passed
        finished_at = datetime.now(timezone.utc)
        duration_seconds = (finished_at - self.started_at).total_seconds()

        scenario_names = [item.get("scenario") for item in self.scenarios]
        exact_scenarios = (
            len(scenario_names) == len(REQUIRED_SCENARIOS)
            and len(set(scenario_names)) == len(REQUIRED_SCENARIOS)
            and set(scenario_names) == set(REQUIRED_SCENARIOS)
        )
        migration_verification = Path(self.migration_verification_path) if self.migration_verification_path else None
        raw_log = Path(self.raw_log_path) if self.raw_log_path else None
        rpo_met = (
            self.rpo_target_seconds > 0
            and self.rpo_actual_seconds is not None
            and self.rpo_actual_seconds <= self.rpo_target_seconds
        )
        rto_met = self.rto_target_seconds > 0 and duration_seconds <= self.rto_target_seconds
        evidence_bound = bool(
            migration_verification
            and migration_verification.is_file()
            and raw_log
            and raw_log.is_file()
        )
        sign_off_complete = (
            self.sign_off.get("decision") == "APPROVED"
            and isinstance(self.sign_off.get("signed_by"), str)
            and bool(self.sign_off.get("signed_by", "").strip())
            and isinstance(self.sign_off.get("signed_at"), str)
            and bool(self.sign_off.get("signed_at", "").strip())
            and isinstance(self.sign_off.get("reason"), str)
            and bool(self.sign_off.get("reason", "").strip())
        )
        attested = (
            self.source_type in ALLOWED_SOURCE_TYPES
            and self.environment == REQUIRED_ENVIRONMENT
            and bool(self.executor_id.strip())
            and rpo_met
            and rto_met
            and evidence_bound
            and sign_off_complete
        )
        if failed:
            outcome = "FAILED"
        elif exact_scenarios and attested:
            outcome = "SUCCEEDED"
        else:
            outcome = "BLOCKED"

        return {
            "schema_version": "tool-defect-production-recovery/v1",
            "drill_id": self.drill_id,
            "source_type": self.source_type,
            "environment": self.environment,
            "executor_id": self.executor_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": duration_seconds,
            "result": outcome,
            "required_scenarios": REQUIRED_SCENARIOS,
            "exact_scenario_set": exact_scenarios,
            "production_attestation_complete": attested,
            "rpo_target_seconds": self.rpo_target_seconds,
            "rpo_actual_seconds": self.rpo_actual_seconds,
            "rto_target_seconds": self.rto_target_seconds,
            "rto_actual_seconds": duration_seconds,
            "migration_verification_path": self.migration_verification_path,
            "migration_verification_sha256": (
                sha256_hex(migration_verification) if migration_verification and migration_verification.is_file() else ""
            ),
            "raw_log_path": self.raw_log_path,
            "raw_log_sha256": sha256_hex(raw_log) if raw_log and raw_log.is_file() else "",
            "sign_off": self.sign_off,
            "scenarios_total": total,
            "scenarios_passed": passed,
            "scenarios_failed": failed,
            "scenarios": self.scenarios,
            "errors": self.errors,
        }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="P7-03 生产恢复演练")
    parser.add_argument("--drill-id", type=str, default=f"drill-{uuid.uuid4().hex[:12]}")
    parser.add_argument("--snapshot-path", type=str, help="备份快照路径")
    parser.add_argument("--migration-verification", type=str, help="全量生产迁移验证报告")
    parser.add_argument("--model-smoke-evidence", type=str, help="生产模型冒烟证据")
    parser.add_argument("--source-type", type=str, default="UNKNOWN")
    parser.add_argument("--environment", type=str, default="UNKNOWN")
    parser.add_argument("--executor-id", type=str, default="")
    parser.add_argument("--rpo-target-seconds", type=float, default=0)
    parser.add_argument("--rto-target-seconds", type=float, default=0)
    parser.add_argument("--raw-log-path", type=str, default="")
    parser.add_argument("--sign-off-record", type=str, default="")
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR))
    parser.add_argument("--json", action="store_true", dest="json_output", help="仅输出 JSON 报告")
    args = parser.parse_args(argv)

    sign_off: Dict[str, Any] = {}
    if args.sign_off_record:
        sign_off_path = Path(args.sign_off_record)
        try:
            parsed_sign_off = json.loads(sign_off_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            print(f"错误: 恢复批准记录不可读: {type(exc).__name__}")
            return 1
        if not isinstance(parsed_sign_off, dict):
            print("错误: 恢复批准记录必须是 JSON 对象。")
            return 1
        sign_off = parsed_sign_off

    orchestrator = RecoveryDrillOrchestrator(
        args.drill_id,
        source_type=args.source_type,
        environment=args.environment,
        executor_id=args.executor_id,
        rpo_target_seconds=args.rpo_target_seconds,
        rto_target_seconds=args.rto_target_seconds,
        migration_verification_path=args.migration_verification or "",
        raw_log_path=args.raw_log_path,
        sign_off=sign_off,
    )

    # Phase 1: 快照验证
    print("Phase 1: 备份快照验证")
    result = orchestrator.verify_snapshot_backup(args.snapshot_path)
    print(f"  {'PASS' if result['passed'] else 'FAIL'}: {result.get('detail', result.get('scenario', ''))}")

    # Phase 2: 隔离恢复
    print("\nPhase 2: 隔离环境恢复")
    with tempfile.TemporaryDirectory(prefix="p7-recovery-drill-") as tmp_target:
        result = orchestrator.verify_isolated_restore(args.snapshot_path or "", tmp_target)
        print(f"  {'PASS' if result['passed'] else 'FAIL'}: files_restored={result.get('detail', {}).get('files_restored', 0) if isinstance(result.get('detail'), dict) else '?'}")

    # Phase 3: 业务验证
    print("\nPhase 3: 业务记录验证")
    db_url = env_optional("DB_URL")
    result = orchestrator.verify_business_records(db_url)
    print(f"  {'PASS' if result['passed'] else 'FAIL'}: tables={result.get('detail', {}).get('tables_checked', []) if isinstance(result.get('detail'), dict) else '?'}")

    # Phase 4: 对象存储验证
    print("\nPhase 4: 对象存储验证")
    result = orchestrator.verify_object_storage(args.migration_verification)
    print(f"  {'PASS' if result['passed'] else 'FAIL'}: full verification evidence")

    # Phase 5: 模型功能验证
    print("\nPhase 5: 模型功能验证")
    result = orchestrator.verify_model_functionality(args.model_smoke_evidence)
    print(f"  {'PASS' if result['passed'] else 'FAIL'}: production smoke evidence")

    # Phase 6: 审批链验证
    print("\nPhase 6: 审批链验证")
    result = orchestrator.verify_approval_chain(db_url)
    print(f"  {'PASS' if result['passed'] else 'FAIL'}")

    report = orchestrator.generate_report()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    record_path = output_dir / "recovery-drill-record.json"
    if record_path.exists():
        print(f"错误: 拒绝覆盖已有恢复演练报告: {record_path}")
        return 1
    record_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    if args.json_output:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"\n演练报告: {record_path}")
        print(f"结果: {report['result']} ({report['scenarios_passed']}/{report['scenarios_total']} 通过)")
        print(f"耗时: {report['duration_seconds']:.1f}s")

    if report["result"] == "SUCCEEDED":
        return 0
    if report["result"] == "BLOCKED":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
