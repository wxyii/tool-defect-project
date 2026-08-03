#!/usr/bin/env python3
"""只读复核 P0 冻结数据、资产清单与现场安全默认值。"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.baseline.decision_checks import validate_files
from tools.baseline.hardcoded_scan import scan_hardcoded_site_parameters
from tools.baseline.inventory import build_inventory, verify_lock


LOCK_PATH = ROOT / "tests/fixtures/baseline/baseline-lock.json"
R2_MIGRATION = (
    ROOT
    / "services/business-api/src/main/resources/db/migration"
    / "V16__r2_unified_detection_core.sql"
)
R3_MIGRATION = R2_MIGRATION.parent / "V17__r3_manual_detection_batches.sql"


def validate_r2_sources() -> list[str]:
    """验证 R2 数据门禁不是空目标或仅有说明文本。"""
    errors: list[str] = []
    migration_dir = R2_MIGRATION.parent
    versions = sorted(
        int(match.group(1))
        for path in migration_dir.glob("V*__*.sql")
        if (match := re.match(r"V([0-9]+)__", path.name))
    )
    expected_versions = list(range(1, max(versions, default=0) + 1))
    if versions != expected_versions or 16 not in versions:
        errors.append(f"数据库迁移序号必须从 V1 连续且包含 R2 V16，实际为 {versions}")
    if not R2_MIGRATION.is_file():
        return errors + ["缺少 R2 的 V16 数据迁移"]

    sql = R2_MIGRATION.read_text(encoding="utf-8")
    required_sql = {
        "统一批次表": "CREATE TABLE detection_batch_v2",
        "单图片项表": "CREATE TABLE detection_batch_item_v2",
        "逐图质量表": "CREATE TABLE image_quality_result_v2",
        "快速反馈表": "CREATE TABLE quick_feedback_v2",
        "管理员反馈表": "CREATE TABLE admin_feedback_v2",
        "独立样本候选表": "CREATE TABLE sample_candidate_v2",
        "样本导出表": "CREATE TABLE sample_export_job_v2",
        "模型上传会话表": "CREATE TABLE model_upload_session_v2",
        "稳定失败清单": "CREATE TABLE r2_migration_failure",
        "影子差异表": "CREATE TABLE r2_shadow_read_difference",
        "安全运行事件": "CREATE TABLE r2_operational_event",
        "幂等回填函数": "td_backfill_legacy_captures_v2()",
        "影子读函数": "td_capture_shadow_differences_v2()",
        "模型来源互斥约束": "ck_model_version_source_complete_exclusive",
        "取消权限撤销": "DELETE FROM sys_role_permission",
    }
    for label, marker in required_sql.items():
        if marker not in sql:
            errors.append(f"V16 缺少{label}：{marker}")

    candidate_match = re.search(
        r"CREATE TABLE sample_candidate_v2\s*\((.*?)\n\);",
        sql,
        re.DOTALL,
    )
    if not candidate_match:
        errors.append("无法解析独立样本候选表")
    elif re.search(r"dataset_version_id|training_run_id", candidate_match.group(1)):
        errors.append("第二版样本候选不得依赖数据集版本或训练运行")

    if "MULTI-VIEW-READ-ONLY" not in sql or "HAVING count(raw.image_id) <> 1" not in sql:
        errors.append("历史多原图必须进入稳定 HOLD 清单，不得自动选择主图")
    if "td_reject_fact_mutation" not in sql:
        errors.append("R2 质量、反馈、失败和差异事实缺少只追加保护")
    if any(token in sql for token in ("detail ? 'image'\n        OR", "detail ? 'token'\n        OR")):
        errors.append("运行事件安全约束结构异常")

    config_path = ROOT / "services/business-api/src/main/resources/application.yaml"
    config = config_path.read_text(encoding="utf-8")
    for marker in (
        "dataset-training-write-enabled: ${TD_LEGACY_DATASET_TRAINING_WRITE_ENABLED:false}",
        "production-v1-write-enabled: ${TD_PRODUCTION_V1_WRITE_ENABLED:true}",
    ):
        if marker not in config:
            errors.append(f"第一版取消写与产线写开关未独立配置：{marker}")

    matrix_path = (
        ROOT
        / "services/business-api/src/main/java/com/tooldefect/business/identity/domain"
        / "RolePermissionMatrix.java"
    )
    matrix = matrix_path.read_text(encoding="utf-8")
    for permission in ("dataset:create", "dataset:approve", "training:create", "training:read"):
        if f'"{permission}"' in matrix:
            errors.append(f"人员角色矩阵仍分配已取消权限：{permission}")
    if '"model:approve"' not in matrix:
        errors.append("模型审批尚未解耦到 model:approve")
    if R3_MIGRATION.is_file():
        r3_sql = R3_MIGRATION.read_text(encoding="utf-8")
        required_r3 = {
            "手工上传会话": "CREATE TABLE manual_batch_upload_v2",
            "单项逻辑检测任务": "CREATE TABLE detection_task_v2",
            "补偿对账事实": "CREATE TABLE r3_compensation_event",
            "手工原图前缀": "object_key LIKE 'manual-originals/%'",
            "补偿事实只追加": "trg_r3_compensation_event_append_only",
            "事实驱动聚合": "td_recompute_detection_batch_v2",
        }
        for label, marker in required_r3.items():
            if marker not in r3_sql:
                errors.append(f"V17 缺少{label}：{marker}")
    return errors


def main() -> int:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    first = build_inventory(ROOT)
    second = build_inventory(ROOT)

    errors: list[str] = []
    if first != second:
        errors.append("连续两次资产扫描结果不一致")
    errors.extend(verify_lock(first, lock))
    errors.extend(validate_files(ROOT))
    errors.extend(
        f"未登记现场硬编码：{finding}"
        for finding in scan_hardcoded_site_parameters(ROOT)
    )
    errors.extend(validate_r2_sources())

    result = {
        "status": "PASSED" if not errors else "FAILED",
        "stable_inventory_sha256": first["stable_inventory_sha256"],
        "raw_image_count": first["asset_groups"]["raw_images"]["file_count"],
        "retraining_sample_count": first["dataset_facts"]["retraining"]["row_count"],
        "audit_test_sample_count": first["dataset_facts"]["retraining_audit"][
            "test_samples"
        ],
        "expected_blocker_count": len(first["blockers"]),
        "r2_migration_version": 16,
        "latest_migration_version": 17 if R3_MIGRATION.is_file() else 16,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
