"""P7-07 上线就绪与 G7 阶段验收的严格验证。"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from tools.p7.common import (
    SHA256,
    ValidationResult,
    is_placeholder,
    read_json_object,
    repository_root,
    valid_iso8601,
    verify_file_evidence,
)


REAL_SOURCE = "REAL_PRODUCTION"
REQUIRED_RELEASE_SIGNOFFS = {"QUALITY", "PROCESS", "ALGORITHM", "RELEASE"}
REQUIRED_TASKS = {f"P7-{number:02d}" for number in range(1, 8)}
REQUIRED_G7_REQUIREMENTS = {
    "real_hardware_network_infrastructure",
    "six_signed_site_parameter_groups",
    "production_model_warmed",
    "stable_previous_model_warmed",
    "rollback_exercised",
    "duty_roster_and_alert_routes",
    "role_manuals_and_external_users",
    "backup_and_isolated_restore",
    "emergency_access_and_certificate_revocation",
}


def _identity(value: Any) -> bool:
    return isinstance(value, str) and not is_placeholder(value)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not valid_iso8601(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _validate_waiver(waiver: Any, result: ValidationResult, label: str) -> None:
    if not isinstance(waiver, dict):
        result.block(f"{label}_waiver_missing")
        return
    if waiver.get("status") != "APPROVED":
        result.block(f"{label}_waiver_not_approved")
    for field in ("owner_id", "approver_id", "compensating_control", "reason"):
        if not _identity(waiver.get(field)):
            result.block(f"{label}_waiver_{field}_missing")
    if not valid_iso8601(waiver.get("expires_at")):
        result.block(f"{label}_waiver_expiry_invalid")
    if not valid_iso8601(waiver.get("approved_at")):
        result.block(f"{label}_waiver_approved_at_invalid")


def validate_repository_release_state(*, repo_root: Path | None = None) -> ValidationResult:
    """确保仓库当前未在阻断条件下声称可上线。"""

    root = (repo_root or repository_root()).resolve()
    result = ValidationResult("p7-repository-release-safety")
    checklist_path = root / "Docs/reports/P7-go-live-checklist.json"
    decision_path = root / "Docs/reports/P7-release-decision-record.json"
    checklist = read_json_object(checklist_path, result, "repository_go_live_checklist")
    decision = read_json_object(decision_path, result, "repository_release_decision")
    if not checklist or not decision:
        return result
    if checklist.get("schema_version") != "tool-defect-go-live-checklist/v1":
        result.error("repository_go_live_schema_invalid")
    if decision.get("schema_version") != "tool-defect-release-decision-record/v1":
        result.error("repository_release_schema_invalid")
    sections = checklist.get("sections")
    items = [
        item
        for section in sections if isinstance(sections, list) and isinstance(section, dict)
        for item in section.get("items", []) if isinstance(item, dict)
    ] if isinstance(sections, list) else []
    has_blockers = any(item.get("status") not in {"PASS", "NOT_APPLICABLE"} for item in items)
    if has_blockers:
        if decision.get("decision") != "NO_GO":
            result.error("repository_release_claims_go_with_open_blockers")
        if decision.get("status") != "BLOCKED":
            result.error("repository_release_status_not_blocked")
    if decision.get("decision") == "CONDITIONAL_GO":
        result.error("repository_conditional_go_forbidden")
    result.checks["checklist_item_count"] = len(items)
    result.checks["has_blockers"] = has_blockers
    result.checks["safe_decision"] = decision.get("decision")
    return result


def _validate_checklist_item(
    item: Any,
    root: Path,
    result: ValidationResult,
    seen: set[str],
) -> tuple[str | None, str | None]:
    if not isinstance(item, dict):
        result.error("go_live_item_not_object")
        return None, None
    item_id = item.get("id")
    if not _identity(item_id) or item_id in seen:
        result.error(f"go_live_item_id_missing_or_duplicate:{item_id}")
        return None, None
    seen.add(item_id)
    status = item.get("status")
    risk = item.get("risk")
    if risk not in {"LOW", "MEDIUM", "HIGH"}:
        result.block(f"go_live_item_risk_invalid:{item_id}")
    if status == "PASS":
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            result.block(f"go_live_item_evidence_missing:{item_id}")
        else:
            for index, descriptor in enumerate(evidence):
                if not isinstance(descriptor, dict):
                    result.block(f"go_live_item_evidence_invalid:{item_id}:{index}")
                    continue
                verify_file_evidence(
                    path_value=descriptor.get("path"),
                    hash_value=descriptor.get("sha256"),
                    base=root,
                    result=result,
                    label=f"go_live_{item_id}_{index}",
                )
    elif status == "NOT_APPLICABLE":
        _validate_waiver(item.get("waiver"), result, f"go_live_{item_id}")
    else:
        result.block(f"go_live_item_not_closed:{item_id}:{status}")
    return status if isinstance(status, str) else None, risk if isinstance(risk, str) else None


def validate_final_go_live_checklist(
    *,
    repo_root: Path | None = None,
    checklist_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    if checklist_path is None:
        configured = os.environ.get("TD_P7_GO_LIVE_CHECKLIST")
        checklist_path = Path(configured) if configured else root / "deploy/environments/production/evidence/go-live-checklist.json"
    result = ValidationResult("p7-final-go-live-checklist")
    checklist = read_json_object(checklist_path, result, "final_go_live_checklist")
    if not checklist:
        return result
    if checklist.get("schema_version") != "tool-defect-go-live-checklist/v2":
        result.block("go_live_schema_invalid")
    if checklist.get("status") != "PASS":
        result.block(f"go_live_status_not_pass:{checklist.get('status')}")
    if checklist.get("source_type") != REAL_SOURCE:
        result.block("go_live_source_not_real_production")
    if checklist.get("contract_version") != "v1":
        result.block("go_live_contract_version_invalid")
    if not _identity(checklist.get("release_id")):
        result.block("go_live_release_id_missing")
    if not valid_iso8601(checklist.get("generated_at")):
        result.block("go_live_generated_at_invalid")
    sections = checklist.get("sections")
    if not isinstance(sections, list) or not sections:
        result.block("go_live_sections_missing")
        return result
    seen: set[str] = set()
    statuses: list[str] = []
    risks: list[str] = []
    for section in sections:
        if not isinstance(section, dict) or not _identity(section.get("id")):
            result.error("go_live_section_invalid")
            continue
        items = section.get("items")
        if not isinstance(items, list) or not items:
            result.block(f"go_live_section_items_missing:{section.get('id')}")
            continue
        for item in items:
            status, risk = _validate_checklist_item(item, root, result, seen)
            if status:
                statuses.append(status)
            if risk:
                risks.append(risk)
    summary = checklist.get("summary")
    expected_summary = {
        "total_items": len(statuses),
        "pass": statuses.count("PASS"),
        "not_applicable": statuses.count("NOT_APPLICABLE"),
        "pending": len([status for status in statuses if status not in {"PASS", "NOT_APPLICABLE"}]),
        "high_risk_items": risks.count("HIGH"),
    }
    if not isinstance(summary, dict):
        result.block("go_live_summary_missing")
    else:
        for field, expected in expected_summary.items():
            if summary.get(field) != expected:
                result.block(f"go_live_summary_mismatch:{field}")
    if expected_summary["pending"] != 0:
        result.block("go_live_pending_items_present")
    result.checks["checklist_path"] = str(checklist_path)
    result.checks["release_id"] = checklist.get("release_id")
    result.checks["item_count"] = len(statuses)
    return result


def _validate_risk_register(risks: Any, result: ValidationResult) -> None:
    if not isinstance(risks, list):
        result.block("release_risk_register_missing")
        return
    seen: set[str] = set()
    for item in risks:
        if not isinstance(item, dict) or not _identity(item.get("id")):
            result.error("release_risk_invalid")
            continue
        risk_id = item["id"]
        if risk_id in seen:
            result.error(f"release_risk_duplicate:{risk_id}")
        seen.add(risk_id)
        severity = item.get("severity")
        status = item.get("status")
        if severity not in {"LOW", "MEDIUM", "HIGH"}:
            result.block(f"release_risk_severity_invalid:{risk_id}")
        if status == "CLOSED":
            if not _identity(item.get("resolution")) or not valid_iso8601(item.get("closed_at")):
                result.block(f"release_risk_closure_incomplete:{risk_id}")
        elif status == "WAIVED" and severity != "HIGH":
            _validate_waiver(item.get("waiver"), result, f"release_risk_{risk_id}")
        else:
            result.block(f"release_risk_not_closed:{risk_id}:{status}")


def _validate_release_signoffs(signoffs: Any, result: ValidationResult) -> None:
    if not isinstance(signoffs, list):
        result.block("release_signoffs_missing")
        return
    by_role = {
        item.get("role"): item
        for item in signoffs
        if isinstance(item, dict) and isinstance(item.get("role"), str)
    }
    if set(by_role) != REQUIRED_RELEASE_SIGNOFFS or len(by_role) != len(signoffs):
        result.block("release_signoff_roles_invalid")
    actors: list[str] = []
    for role in sorted(REQUIRED_RELEASE_SIGNOFFS):
        item = by_role.get(role)
        if not isinstance(item, dict):
            continue
        if item.get("decision") != "APPROVED":
            result.block(f"release_signoff_not_approved:{role}")
        actor = item.get("actor_id")
        if not _identity(actor):
            result.block(f"release_signoff_actor_missing:{role}")
        else:
            actors.append(actor)
        if not valid_iso8601(item.get("signed_at")):
            result.block(f"release_signoff_time_invalid:{role}")
        if is_placeholder(item.get("reason")):
            result.block(f"release_signoff_reason_missing:{role}")
    if len(set(actors)) != len(REQUIRED_RELEASE_SIGNOFFS):
        result.block("release_signoff_actors_not_distinct")


def validate_final_release_decision(
    *,
    repo_root: Path | None = None,
    decision_path: Path | None = None,
    checklist_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    if decision_path is None:
        configured = os.environ.get("TD_P7_RELEASE_DECISION")
        decision_path = Path(configured) if configured else root / "deploy/environments/production/evidence/release-decision-record.json"
    expected_checklist = checklist_path or (
        Path(os.environ["TD_P7_GO_LIVE_CHECKLIST"])
        if os.environ.get("TD_P7_GO_LIVE_CHECKLIST")
        else root / "deploy/environments/production/evidence/go-live-checklist.json"
    )
    result = ValidationResult("p7-final-release-decision")
    decision = read_json_object(decision_path, result, "final_release_decision")
    if not decision:
        return result
    if decision.get("schema_version") != "tool-defect-release-decision-record/v2":
        result.block("release_decision_schema_invalid")
    if decision.get("status") != "APPROVED":
        result.block(f"release_decision_status_invalid:{decision.get('status')}")
    if decision.get("decision") != "GO":
        result.block(f"release_decision_not_go:{decision.get('decision')}")
    if decision.get("source_type") != REAL_SOURCE:
        result.block("release_decision_source_not_real")
    if decision.get("contract_version") != "v1":
        result.block("release_decision_contract_version_invalid")
    for field in ("release_id", "release_version", "current_model_version_id"):
        if not _identity(decision.get(field)):
            result.block(f"release_decision_{field}_missing")
    for field in ("decided_at", "release_at"):
        if not valid_iso8601(decision.get(field)):
            result.block(f"release_decision_{field}_invalid")
    if decision.get("conditions_met") is not True:
        result.block("release_conditions_not_met")

    bound_checklist = verify_file_evidence(
        path_value=decision.get("checklist_path"),
        hash_value=decision.get("checklist_sha256"),
        base=root,
        result=result,
        label="release_bound_checklist",
    )
    if bound_checklist is not None and bound_checklist != expected_checklist.resolve():
        result.block("release_bound_checklist_wrong_path")

    task_results = decision.get("task_results")
    if not isinstance(task_results, dict) or set(task_results) != {f"P7-{number:02d}" for number in range(1, 7)}:
        result.block("release_task_results_invalid")
    else:
        for task_id, item in task_results.items():
            if not isinstance(item, dict) or item.get("status") != "PASS":
                result.block(f"release_task_not_pass:{task_id}")
                continue
            verify_file_evidence(
                path_value=item.get("evidence_path"),
                hash_value=item.get("evidence_sha256"),
                base=root,
                result=result,
                label=f"release_{task_id}",
            )

    _validate_risk_register(decision.get("risk_register"), result)
    rollback = decision.get("rollback_target")
    if not isinstance(rollback, dict):
        result.block("release_rollback_target_missing")
    else:
        if not _identity(rollback.get("model_version_id")) or rollback.get("model_version_id") == decision.get("current_model_version_id"):
            result.block("release_rollback_model_identity_invalid")
        package_hash = rollback.get("package_sha256")
        if not isinstance(package_hash, str) or SHA256.fullmatch(package_hash) is None:
            result.block("release_rollback_package_hash_invalid")
        if rollback.get("registry_alias") != "stable-previous":
            result.block("release_rollback_alias_invalid")
        for field in ("signature_verified", "warmed", "health_ready", "rollback_exercised"):
            if rollback.get(field) is not True:
                result.block(f"release_rollback_{field}_missing")
        verify_file_evidence(
            path_value=rollback.get("evidence_path"),
            hash_value=rollback.get("evidence_sha256"),
            base=root,
            result=result,
            label="release_rollback_evidence",
        )

    roster = decision.get("duty_roster")
    if not isinstance(roster, dict) or roster.get("status") != "ACTIVE":
        result.block("release_duty_roster_not_active")
    else:
        roster_start = _timestamp(roster.get("starts_at"))
        roster_end = _timestamp(roster.get("ends_at"))
        release_at = _timestamp(decision.get("release_at"))
        if roster_start is None or roster_end is None or release_at is None:
            result.block("release_duty_roster_window_invalid")
        elif roster_start > release_at or roster_end < release_at + timedelta(days=7):
            result.block("release_duty_roster_window_insufficient")
        if roster.get("coverage_complete") is not True or roster.get("uncovered_seconds") != 0:
            result.block("release_duty_roster_coverage_incomplete")
        slots = roster.get("slots")
        if not isinstance(slots, list) or not slots:
            result.block("release_duty_roster_slots_missing")
        else:
            for index, slot in enumerate(slots):
                if not isinstance(slot, dict):
                    result.block(f"release_duty_roster_slot_invalid:{index}")
                    continue
                for role in ("operations_actor_id", "quality_actor_id", "algorithm_actor_id"):
                    if not _identity(slot.get(role)):
                        result.block(f"release_duty_roster_role_missing:{index}:{role}")
        verify_file_evidence(
            path_value=roster.get("evidence_path"),
            hash_value=roster.get("evidence_sha256"),
            base=root,
            result=result,
            label="release_duty_roster_evidence",
        )

    _validate_release_signoffs(decision.get("sign_offs"), result)
    verify_file_evidence(
        path_value=decision.get("raw_log_path"),
        hash_value=decision.get("raw_log_sha256"),
        base=root,
        result=result,
        label="release_decision_raw_log",
    )
    result.checks["decision_path"] = str(decision_path)
    result.checks["release_id"] = decision.get("release_id")
    return result


def validate_p7_07_evidence(*, repo_root: Path | None = None) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    result = ValidationResult("p7-go-live-readiness")
    result.merge(validate_repository_release_state(repo_root=root), "repository_state")
    checklist = validate_final_go_live_checklist(repo_root=root)
    decision = validate_final_release_decision(repo_root=root)
    result.merge(checklist, "checklist")
    result.merge(decision, "decision")
    checklist_release = checklist.checks.get("release_id")
    decision_release = decision.checks.get("release_id")
    if checklist_release and decision_release and checklist_release != decision_release:
        result.block("release_id_mismatch_between_checklist_and_decision")
    result.checks["contract_version"] = "v1"
    return result


def validate_g7_record(
    *,
    repo_root: Path | None = None,
    report_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    if report_path is None:
        configured = os.environ.get("TD_G7_EVIDENCE")
        report_path = Path(configured) if configured else root / "Docs/reports/P7-gate-acceptance.json"
    result = ValidationResult("g7-stage-acceptance")
    report = read_json_object(report_path, result, "g7_acceptance")
    if not report:
        return result
    if report.get("schema_version") != "tool-defect-p7-gate-acceptance/v1":
        result.block("g7_schema_invalid")
    if report.get("status") != "PASS":
        result.block(f"g7_status_not_pass:{report.get('status')}")
    if report.get("production_claim_allowed") is not True:
        result.block("g7_production_claim_not_allowed")
    if report.get("contract_version") != "v1":
        result.block("g7_contract_version_invalid")
    if report.get("source_type") != REAL_SOURCE:
        result.block("g7_source_not_real_production")
    for field in ("gate_id", "release_id"):
        if not _identity(report.get(field)):
            result.block(f"g7_{field}_missing")
    if not valid_iso8601(report.get("generated_at")):
        result.block("g7_generated_at_invalid")

    tasks = report.get("task_results")
    if not isinstance(tasks, list):
        result.block("g7_task_results_missing")
    else:
        by_task = {
            item.get("task_id"): item
            for item in tasks
            if isinstance(item, dict) and isinstance(item.get("task_id"), str)
        }
        if set(by_task) != REQUIRED_TASKS or len(by_task) != len(tasks):
            result.block("g7_task_result_set_invalid")
        for task_id in sorted(REQUIRED_TASKS):
            item = by_task.get(task_id)
            if not isinstance(item, dict) or item.get("status") != "PASS":
                result.block(f"g7_task_not_pass:{task_id}")
                continue
            verify_file_evidence(
                path_value=item.get("evidence_path"),
                hash_value=item.get("evidence_sha256"),
                base=root,
                result=result,
                label=f"g7_{task_id}",
            )

    requirements = report.get("requirements")
    if not isinstance(requirements, dict) or set(requirements) != REQUIRED_G7_REQUIREMENTS:
        result.block("g7_requirement_set_invalid")
    else:
        for name in sorted(REQUIRED_G7_REQUIREMENTS):
            item = requirements.get(name)
            if not isinstance(item, dict) or item.get("status") != "PASS":
                result.block(f"g7_requirement_not_pass:{name}")
                continue
            verify_file_evidence(
                path_value=item.get("evidence_path"),
                hash_value=item.get("evidence_sha256"),
                base=root,
                result=result,
                label=f"g7_requirement_{name}",
            )
    _validate_release_signoffs(report.get("sign_offs"), result)
    verify_file_evidence(
        path_value=report.get("raw_log_path"),
        hash_value=report.get("raw_log_sha256"),
        base=root,
        result=result,
        label="g7_raw_log",
    )
    result.checks["report_path"] = str(report_path)
    return result
