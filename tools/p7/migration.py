"""P7-03 生产迁移与恢复证据的严格只读验证。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.p7.common import (
    SHA256,
    ValidationResult,
    is_placeholder,
    read_json_object,
    repository_root,
    sha256_file,
    valid_iso8601,
    verify_file_evidence,
)


REAL_SOURCE = "REAL_PRODUCTION"
REQUIRED_PHASES = {
    "verify_source",
    "migrate_objects",
    "register_database",
    "verify_counts",
}
REQUIRED_ARTIFACT_GROUPS = {
    "images",
    "masks",
    "datasets",
    "models",
    "database",
    "approvals",
}
REQUIRED_RECOVERY_SCENARIOS = {
    "snapshot_backup",
    "isolated_restore",
    "business_records",
    "object_storage",
    "model_functionality",
    "approval_chain",
}


def _positive_identity(value: Any) -> bool:
    return isinstance(value, str) and not is_placeholder(value)


def _validate_source_summary(summary: Any, result: ValidationResult) -> None:
    if not isinstance(summary, dict):
        result.block("migration_source_summary_missing")
        return
    if summary.get("overall_status") != "COMPLETE":
        result.block(f"migration_source_not_complete:{summary.get('overall_status')}")
    if summary.get("production_claim_allowed") is not True:
        result.block("migration_source_production_claim_not_allowed")
    manifests = summary.get("manifests")
    baseline = manifests.get("baseline-180") if isinstance(manifests, dict) else None
    if not isinstance(baseline, dict) or baseline.get("status") != "COMPLETE":
        result.block("migration_baseline_not_complete")
        return
    for field in (
        "file_errors",
        "cross_split_issues",
        "family_leak_issues",
        "label_consistency_issues",
    ):
        if baseline.get(field) != 0:
            result.block(f"migration_baseline_{field}_not_zero")


def validate_migration_report(
    *,
    repo_root: Path | None = None,
    report_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    report_path = report_path or root / "deploy/environments/production/evidence/production-migration-report.json"
    result = ValidationResult("p7-production-migration-report")
    report = read_json_object(report_path, result, "production_migration_report")
    if not report:
        return result

    if report.get("schema_version") != "tool-defect-production-migration/v1":
        result.block("migration_report_schema_invalid")
    if report.get("execution_mode") != "EXECUTE":
        result.block(f"migration_execution_mode_invalid:{report.get('execution_mode')}")
    if report.get("source_type") != REAL_SOURCE:
        result.block("migration_source_not_real_production")
    if report.get("production_claim_allowed") is not True:
        result.block("migration_production_claim_not_allowed")
    if not _positive_identity(report.get("migration_id")):
        result.block("migration_id_missing")
    for field in ("started_at", "finished_at", "generated_at"):
        if not valid_iso8601(report.get(field)):
            result.block(f"migration_{field}_invalid")
    if not _positive_identity(report.get("executor_id")):
        result.block("migration_executor_id_missing")

    summary = report.get("summary")
    if not isinstance(summary, dict) or summary.get("overall_status") != "COMPLETE":
        result.block("migration_summary_not_complete")
    _validate_source_summary(report.get("source_summary"), result)

    phases = report.get("phases")
    if not isinstance(phases, dict):
        result.block("migration_phases_missing")
    else:
        missing = sorted(REQUIRED_PHASES.difference(phases))
        if missing:
            result.block(f"migration_phases_missing:{','.join(missing)}")
        for phase in sorted(REQUIRED_PHASES):
            item = phases.get(phase)
            if not isinstance(item, dict) or item.get("status") != "PASSED":
                result.block(f"migration_phase_not_pass:{phase}")
            if isinstance(item, dict) and item.get("errors") not in ([], None):
                result.block(f"migration_phase_has_errors:{phase}")

    snapshot = report.get("source_snapshot")
    if not isinstance(snapshot, dict):
        result.block("migration_source_snapshot_missing")
    else:
        if not _positive_identity(snapshot.get("snapshot_id")):
            result.block("migration_source_snapshot_id_missing")
        verify_file_evidence(
            path_value=snapshot.get("manifest_path"),
            hash_value=snapshot.get("manifest_sha256"),
            base=root,
            result=result,
            label="migration_source_manifest",
        )
        verify_file_evidence(
            path_value=snapshot.get("preservation_log_path"),
            hash_value=snapshot.get("preservation_log_sha256"),
            base=root,
            result=result,
            label="migration_source_preservation_log",
        )
        if snapshot.get("source_deleted") is not False:
            result.block("migration_source_deletion_not_disproved")

    rollback = report.get("rollback")
    if not isinstance(rollback, dict):
        result.block("migration_rollback_evidence_missing")
    else:
        if rollback.get("scoped_to_migration_id") is not True:
            result.block("migration_rollback_not_batch_scoped")
        if rollback.get("source_preserved") is not True:
            result.block("migration_rollback_source_not_preserved")
        if rollback.get("uses_unscoped_delete") is not False:
            result.block("migration_rollback_unscoped_delete_not_rejected")
        verify_file_evidence(
            path_value=rollback.get("plan_path"),
            hash_value=rollback.get("plan_sha256"),
            base=root,
            result=result,
            label="migration_rollback_plan",
        )

    result.checks["report_path"] = str(report_path)
    result.checks["migration_id"] = report.get("migration_id")
    return result


def _validate_artifact_group(name: str, item: Any, result: ValidationResult) -> None:
    if not isinstance(item, dict):
        result.block(f"migration_verification_artifact_missing:{name}")
        return
    if item.get("status") != "PASS":
        result.block(f"migration_verification_artifact_not_pass:{name}")
    for prefix in ("count", "bytes"):
        source = item.get(f"source_{prefix}")
        target = item.get(f"target_{prefix}")
        if not isinstance(source, int) or isinstance(source, bool) or source < 0:
            result.block(f"migration_verification_{name}_source_{prefix}_invalid")
        if target != source:
            result.block(f"migration_verification_{name}_{prefix}_mismatch")
    source_hash = item.get("source_sha256")
    target_hash = item.get("target_sha256")
    if not isinstance(source_hash, str) or SHA256.fullmatch(source_hash) is None:
        result.block(f"migration_verification_{name}_source_sha256_invalid")
    if target_hash != source_hash:
        result.block(f"migration_verification_{name}_sha256_mismatch")


def validate_migration_verification(
    *,
    repo_root: Path | None = None,
    report_path: Path | None = None,
    migration_report_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    report_path = report_path or root / "deploy/environments/production/evidence/production-migration-verification.json"
    expected_migration_path = migration_report_path or root / "deploy/environments/production/evidence/production-migration-report.json"
    result = ValidationResult("p7-production-migration-verification")
    report = read_json_object(report_path, result, "production_migration_verification")
    if not report:
        return result

    if report.get("schema_version") != "tool-defect-production-migration-verification/v1":
        result.block("migration_verification_schema_invalid")
    if report.get("overall_status") != "PASS":
        result.block(f"migration_verification_not_pass:{report.get('overall_status')}")
    if report.get("source_type") != REAL_SOURCE:
        result.block("migration_verification_source_not_real")
    if report.get("verification_scope") != "FULL":
        result.block("migration_verification_scope_not_full")
    if not _positive_identity(report.get("migration_id")):
        result.block("migration_verification_id_missing")
    if not _positive_identity(report.get("executor_id")):
        result.block("migration_verification_executor_missing")
    for field in ("started_at", "finished_at"):
        if not valid_iso8601(report.get(field)):
            result.block(f"migration_verification_{field}_invalid")

    bound_report = verify_file_evidence(
        path_value=report.get("migration_report_path"),
        hash_value=report.get("migration_report_sha256"),
        base=root,
        result=result,
        label="migration_verification_bound_report",
    )
    if bound_report is not None and bound_report != expected_migration_path.resolve():
        result.block("migration_verification_bound_report_wrong_path")

    artifacts = report.get("artifacts")
    if not isinstance(artifacts, dict):
        result.block("migration_verification_artifacts_missing")
    else:
        for name in sorted(REQUIRED_ARTIFACT_GROUPS):
            _validate_artifact_group(name, artifacts.get(name), result)

    object_storage = report.get("categories", {}).get("object_storage") if isinstance(report.get("categories"), dict) else None
    if not isinstance(object_storage, dict) or object_storage.get("status") != "PASS":
        result.block("migration_verification_object_storage_not_pass")
    else:
        expected_objects = object_storage.get("expected_objects")
        if not isinstance(expected_objects, int) or isinstance(expected_objects, bool) or expected_objects <= 0:
            result.block("migration_verification_expected_objects_invalid")
        if object_storage.get("verified_objects") != expected_objects:
            result.block("migration_verification_object_count_mismatch")
        if object_storage.get("missing_objects") != 0:
            result.block("migration_verification_missing_objects")
        if object_storage.get("hash_mismatches") != 0:
            result.block("migration_verification_object_hash_mismatch")
        expected_bytes = object_storage.get("expected_bytes")
        if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes <= 0:
            result.block("migration_verification_expected_bytes_invalid")
        if object_storage.get("verified_bytes") != expected_bytes:
            result.block("migration_verification_object_bytes_mismatch")

    preservation = report.get("source_preservation")
    if not isinstance(preservation, dict) or preservation.get("status") != "PASS":
        result.block("migration_source_preservation_not_pass")
    else:
        if preservation.get("source_read_only") is not True:
            result.block("migration_source_not_read_only")
        if preservation.get("source_deleted") is not False:
            result.block("migration_source_deleted_not_false")
        verify_file_evidence(
            path_value=preservation.get("postcheck_path"),
            hash_value=preservation.get("postcheck_sha256"),
            base=root,
            result=result,
            label="migration_source_postcheck",
        )

    verify_file_evidence(
        path_value=report.get("raw_log_path"),
        hash_value=report.get("raw_log_sha256"),
        base=root,
        result=result,
        label="migration_verification_raw_log",
    )
    result.checks["report_path"] = str(report_path)
    result.checks["migration_id"] = report.get("migration_id")
    return result


def validate_recovery_report(
    *,
    repo_root: Path | None = None,
    report_path: Path | None = None,
    verification_report_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    report_path = report_path or root / "deploy/environments/production/evidence/recovery-drill-record.json"
    expected_verification = verification_report_path or root / "deploy/environments/production/evidence/production-migration-verification.json"
    result = ValidationResult("p7-production-recovery-report")
    report = read_json_object(report_path, result, "production_recovery_report")
    if not report:
        return result

    if report.get("schema_version") != "tool-defect-production-recovery/v1":
        result.block("recovery_schema_invalid")
    if report.get("result") != "SUCCEEDED":
        result.block(f"recovery_not_succeeded:{report.get('result')}")
    if report.get("source_type") != REAL_SOURCE:
        result.block("recovery_source_not_real_production")
    if report.get("environment") != "ISOLATED_PRODUCTION_EQUIVALENT":
        result.block("recovery_environment_not_isolated_production_equivalent")
    if report.get("production_attestation_complete") is not True:
        result.block("recovery_production_attestation_missing")
    if report.get("exact_scenario_set") is not True:
        result.block("recovery_exact_scenario_set_not_confirmed")
    if not _positive_identity(report.get("drill_id")):
        result.block("recovery_drill_id_missing")
    if not _positive_identity(report.get("executor_id")):
        result.block("recovery_executor_missing")
    for field in ("started_at", "finished_at"):
        if not valid_iso8601(report.get(field)):
            result.block(f"recovery_{field}_invalid")

    scenarios = report.get("scenarios")
    if not isinstance(scenarios, list):
        result.block("recovery_scenarios_missing")
    else:
        names = [item.get("scenario") for item in scenarios if isinstance(item, dict)]
        if len(names) != len(REQUIRED_RECOVERY_SCENARIOS) or set(names) != REQUIRED_RECOVERY_SCENARIOS:
            result.block("recovery_scenario_set_invalid")
        for item in scenarios:
            if not isinstance(item, dict) or item.get("passed") is not True:
                result.block(f"recovery_scenario_not_pass:{item.get('scenario') if isinstance(item, dict) else 'invalid'}")

    for metric in ("rpo", "rto"):
        target = report.get(f"{metric}_target_seconds")
        actual = report.get(f"{metric}_actual_seconds")
        if not isinstance(target, (int, float)) or isinstance(target, bool) or target <= 0:
            result.block(f"recovery_{metric}_target_invalid")
        if not isinstance(actual, (int, float)) or isinstance(actual, bool) or actual < 0:
            result.block(f"recovery_{metric}_actual_invalid")
        elif isinstance(target, (int, float)) and not isinstance(target, bool) and target > 0 and actual > target:
            result.block(f"recovery_{metric}_target_missed")

    bound_verification = verify_file_evidence(
        path_value=report.get("migration_verification_path"),
        hash_value=report.get("migration_verification_sha256"),
        base=root,
        result=result,
        label="recovery_bound_migration_verification",
    )
    if bound_verification is not None and bound_verification != expected_verification.resolve():
        result.block("recovery_bound_verification_wrong_path")
    verify_file_evidence(
        path_value=report.get("raw_log_path"),
        hash_value=report.get("raw_log_sha256"),
        base=root,
        result=result,
        label="recovery_raw_log",
    )

    sign_off = report.get("sign_off")
    if not isinstance(sign_off, dict):
        result.block("recovery_sign_off_missing")
    else:
        if sign_off.get("decision") != "APPROVED":
            result.block("recovery_sign_off_not_approved")
        if not _positive_identity(sign_off.get("signed_by")):
            result.block("recovery_signer_missing")
        if not valid_iso8601(sign_off.get("signed_at")):
            result.block("recovery_signed_at_invalid")
        if is_placeholder(sign_off.get("reason")):
            result.block("recovery_sign_off_reason_missing")

    result.checks["report_path"] = str(report_path)
    result.checks["report_sha256"] = sha256_file(report_path)
    return result


def validate_p7_03_evidence(*, repo_root: Path | None = None) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    result = ValidationResult("p7-production-migration-and-recovery")
    migration_path = root / "deploy/environments/production/evidence/production-migration-report.json"
    verification_path = root / "deploy/environments/production/evidence/production-migration-verification.json"
    recovery_path = root / "deploy/environments/production/evidence/recovery-drill-record.json"
    migration = validate_migration_report(repo_root=root, report_path=migration_path)
    verification = validate_migration_verification(
        repo_root=root,
        report_path=verification_path,
        migration_report_path=migration_path,
    )
    recovery = validate_recovery_report(
        repo_root=root,
        report_path=recovery_path,
        verification_report_path=verification_path,
    )
    result.merge(migration, "migration")
    result.merge(verification, "verification")
    result.merge(recovery, "recovery")

    migration_id = migration.checks.get("migration_id")
    verification_id = verification.checks.get("migration_id")
    if migration_id and verification_id and migration_id != verification_id:
        result.block("migration_id_mismatch_between_reports")
    result.checks["contract_version"] = "v1"
    return result
