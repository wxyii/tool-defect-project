"""P7-06 角色手册、联系人和真实应急演练证据验证。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.p7.common import (
    ValidationResult,
    is_placeholder,
    read_json_object,
    repository_root,
    valid_iso8601,
    verify_file_evidence,
)


REAL_SOURCES = {"REAL_PRODUCTION", "REAL_PRODUCTION_EQUIPMENT"}
REQUIRED_MANUALS = {
    "OPERATOR": "operator-manual.md",
    "REVIEWER": "reviewer-manual.md",
    "QUALITY": "quality-lead-manual.md",
    "ALGORITHM": "algorithm-manual.md",
    "RELEASE": "release-manual.md",
    "ADMINISTRATOR": "administrator-manual.md",
    "AUDITOR": "auditor-manual.md",
    "OPERATIONS": "ops-manual.md",
    "SECURITY": "security-manual.md",
}
MANUAL_CONTROLS = (
    "所需权限",
    "操作原因",
    "二次确认",
    "审计事件",
    "HOLD",
)
REQUIRED_CONTACT_ROLES = {
    "ops_lead",
    "security_lead",
    "quality_lead",
    "edge_lead",
    "infra_lead",
    "algorithm_lead",
    "release_lead",
    "process_lead",
}
REQUIRED_P7_SCENARIOS = {
    "DRILL-15": "NORMAL_OPERATION",
    "DRILL-16": "PERMISSION_DENIAL",
    "DRILL-17": "DEAD_LETTER",
    "DRILL-18": "FULL_ROLLBACK",
    "DRILL-19": "CERTIFICATE_REVOCATION",
    "DRILL-20": "EMERGENCY_ACCOUNT",
}
HIGH_RISK_SCENARIOS = {"DRILL-16", "DRILL-17", "DRILL-18", "DRILL-19", "DRILL-20"}
REQUIRED_SIGNOFF_ROLES = {"OPERATIONS", "QUALITY", "SECURITY", "AUDIT"}


def _identity(value: Any) -> bool:
    return isinstance(value, str) and not is_placeholder(value)


def validate_role_manuals(*, repo_root: Path | None = None) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    result = ValidationResult("p7-role-manuals")
    manual_root = root / "Docs/runbooks"
    for role, filename in REQUIRED_MANUALS.items():
        path = manual_root / filename
        if not path.is_file():
            result.block(f"role_manual_missing:{role}:{filename}")
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            result.error(f"role_manual_unreadable:{role}:{type(exc).__name__}")
            continue
        for control in MANUAL_CONTROLS:
            if control not in body:
                result.block(f"role_manual_control_missing:{role}:{control}")
        if "不得" not in body and "禁止" not in body:
            result.block(f"role_manual_prohibition_missing:{role}")
    result.checks["manual_count"] = len(REQUIRED_MANUALS)
    return result


def validate_scenario_catalog(*, repo_root: Path | None = None) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    result = ValidationResult("p7-emergency-scenario-catalog")
    path = root / "Docs/runbooks/emergency-drill-scenarios.json"
    payload = read_json_object(path, result, "emergency_scenario_catalog")
    if not payload:
        return result
    if payload.get("schema_version") != "tool-defect-emergency-drill/v1":
        result.block("emergency_scenario_schema_invalid")
    if payload.get("drill_environment") != "REAL_PRODUCTION_EQUIPMENT":
        result.block("emergency_scenario_environment_not_real_equipment")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list):
        result.block("emergency_scenarios_missing")
        return result
    by_id = {
        item.get("id"): item
        for item in scenarios
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if len(by_id) != len(scenarios):
        result.block("emergency_scenario_id_duplicate_or_invalid")
    if len(by_id) < 20:
        result.block("emergency_scenario_count_insufficient")
    for scenario_id, scenario_type in REQUIRED_P7_SCENARIOS.items():
        item = by_id.get(scenario_id)
        if not isinstance(item, dict):
            result.block(f"emergency_required_scenario_missing:{scenario_id}")
            continue
        if item.get("scenario_type") != scenario_type:
            result.block(f"emergency_scenario_type_invalid:{scenario_id}")
        if item.get("requires_reason") is not True:
            result.block(f"emergency_scenario_reason_control_missing:{scenario_id}")
        if item.get("requires_second_confirmation") is not True:
            result.block(f"emergency_scenario_confirmation_control_missing:{scenario_id}")
        if item.get("requires_audit") is not True:
            result.block(f"emergency_scenario_audit_control_missing:{scenario_id}")
        for field in ("trigger", "expected_system_behavior"):
            if not _identity(item.get(field)):
                result.block(f"emergency_scenario_{field}_missing:{scenario_id}")
        for field in ("recovery_steps", "success_criteria", "required_participants"):
            values = item.get(field)
            if not isinstance(values, list) or len(values) < 2:
                result.block(f"emergency_scenario_{field}_insufficient:{scenario_id}")
        reference = item.get("runbook_ref")
        if not isinstance(reference, str) or not (root / "Docs/runbooks" / reference).is_file():
            result.block(f"emergency_scenario_runbook_missing:{scenario_id}")
    result.checks["scenario_ids"] = sorted(by_id)
    return result


def validate_emergency_contacts(
    *,
    repo_root: Path | None = None,
    contacts_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    contacts_path = contacts_path or root / "deploy/environments/production/evidence/emergency-contacts.json"
    result = ValidationResult("p7-emergency-contacts")
    payload = read_json_object(contacts_path, result, "emergency_contacts")
    if not payload:
        return result
    if payload.get("schema_version") != "tool-defect-emergency-contacts/v1":
        result.block("emergency_contacts_schema_invalid")
    if payload.get("status") != "ACTIVE":
        result.block(f"emergency_contacts_not_active:{payload.get('status')}")
    if payload.get("source_type") != "REAL_PRODUCTION":
        result.block("emergency_contacts_source_not_real")
    if not valid_iso8601(payload.get("verified_at")):
        result.block("emergency_contacts_verified_at_invalid")
    channels = payload.get("communication_channels")
    if not isinstance(channels, dict):
        result.block("emergency_contact_channels_missing")
    else:
        for name in ("primary", "backup"):
            item = channels.get(name)
            if not isinstance(item, dict) or item.get("status") != "ACTIVE":
                result.block(f"emergency_contact_channel_not_active:{name}")
            elif not _identity(item.get("type")) or not _identity(item.get("details")):
                result.block(f"emergency_contact_channel_incomplete:{name}")
    roles = payload.get("roles")
    if not isinstance(roles, dict):
        result.block("emergency_contact_roles_missing")
    else:
        if set(roles) != REQUIRED_CONTACT_ROLES:
            result.block("emergency_contact_role_set_invalid")
        actors: set[str] = set()
        for role in sorted(REQUIRED_CONTACT_ROLES):
            item = roles.get(role)
            if not isinstance(item, dict):
                continue
            for field in ("actor_id", "name", "phone", "email"):
                if not _identity(item.get(field)):
                    result.block(f"emergency_contact_{field}_missing:{role}")
            actor = item.get("actor_id")
            if isinstance(actor, str) and actor in actors:
                result.block(f"emergency_contact_actor_duplicate:{actor}")
            if isinstance(actor, str):
                actors.add(actor)
            if item.get("on_call") is not True:
                result.block(f"emergency_contact_not_on_call:{role}")
            if not valid_iso8601(item.get("verified_at")):
                result.block(f"emergency_contact_role_verified_at_invalid:{role}")
    verify_file_evidence(
        path_value=payload.get("duty_roster_path"),
        hash_value=payload.get("duty_roster_sha256"),
        base=root,
        result=result,
        label="emergency_duty_roster",
    )
    result.checks["contacts_path"] = str(contacts_path)
    return result


def _validate_participants(report: dict[str, Any], result: ValidationResult) -> dict[str, dict[str, Any]]:
    participants = report.get("participants")
    if not isinstance(participants, list):
        result.block("operations_drill_participants_missing")
        return {}
    by_role = {
        item.get("role"): item
        for item in participants
        if isinstance(item, dict) and isinstance(item.get("role"), str)
    }
    if set(by_role) != set(REQUIRED_MANUALS) or len(by_role) != len(participants):
        result.block("operations_drill_participant_roles_invalid")
    actors: set[str] = set()
    for role, item in by_role.items():
        actor = item.get("actor_id")
        if not _identity(actor):
            result.block(f"operations_drill_participant_actor_missing:{role}")
        elif actor in actors:
            result.block(f"operations_drill_participant_actor_duplicate:{actor}")
        else:
            actors.add(actor)
        if item.get("external_user") is not True or item.get("involved_in_development") is not False:
            result.block(f"operations_drill_participant_not_external:{role}")
        if item.get("training_completed") is not True:
            result.block(f"operations_drill_training_not_complete:{role}")
        if not valid_iso8601(item.get("training_completed_at")):
            result.block(f"operations_drill_training_time_invalid:{role}")
    return by_role


def _validate_special_scenario(scenario_id: str, item: dict[str, Any], result: ValidationResult) -> None:
    if scenario_id == "DRILL-15":
        if item.get("normal_workflow_complete") is not True or item.get("traceability_complete") is not True:
            result.block("operations_normal_workflow_not_complete")
    elif scenario_id == "DRILL-16":
        if item.get("all_unauthorized_requests_denied") is not True or item.get("state_changes") != 0:
            result.block("operations_permission_denial_not_proven")
    elif scenario_id == "DRILL-17":
        if (
            item.get("blind_bulk_replay") is not False
            or item.get("unreconciled_duplicates") != 0
            or item.get("unrecoverable_state") != "HOLD"
        ):
            result.block("operations_dead_letter_control_not_proven")
    elif scenario_id == "DRILL-18":
        for field in ("stable_previous_warmed", "history_unchanged", "rollback_completed"):
            if item.get(field) is not True:
                result.block(f"operations_rollback_{field}_missing")
    elif scenario_id == "DRILL-19":
        if item.get("revoked_certificate_denied") is not True or item.get("device_state") != "HOLD":
            result.block("operations_certificate_revocation_not_proven")
    elif scenario_id == "DRILL-20":
        for field in ("dual_approval", "least_privilege", "account_disabled_after", "credentials_rotated"):
            if item.get(field) is not True:
                result.block(f"operations_emergency_account_{field}_missing")


def _validate_signoffs(report: dict[str, Any], result: ValidationResult) -> None:
    signoffs = report.get("sign_offs")
    if not isinstance(signoffs, list):
        result.block("operations_drill_signoffs_missing")
        return
    by_role = {
        item.get("role"): item
        for item in signoffs
        if isinstance(item, dict) and isinstance(item.get("role"), str)
    }
    if set(by_role) != REQUIRED_SIGNOFF_ROLES or len(by_role) != len(signoffs):
        result.block("operations_drill_signoff_roles_invalid")
    actors: list[str] = []
    for role in sorted(REQUIRED_SIGNOFF_ROLES):
        item = by_role.get(role)
        if not isinstance(item, dict):
            continue
        if item.get("decision") != "APPROVED":
            result.block(f"operations_drill_signoff_not_approved:{role}")
        actor = item.get("actor_id")
        if not _identity(actor):
            result.block(f"operations_drill_signoff_actor_missing:{role}")
        else:
            actors.append(actor)
        if not valid_iso8601(item.get("signed_at")):
            result.block(f"operations_drill_signoff_time_invalid:{role}")
        if is_placeholder(item.get("reason")):
            result.block(f"operations_drill_signoff_reason_missing:{role}")
    if len(set(actors)) != len(REQUIRED_SIGNOFF_ROLES):
        result.block("operations_drill_signoff_actors_not_distinct")


def validate_operations_drill(
    *,
    repo_root: Path | None = None,
    report_path: Path | None = None,
    contacts_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    report_path = report_path or root / "deploy/environments/production/evidence/user-operations-drill.json"
    expected_contacts = contacts_path or root / "deploy/environments/production/evidence/emergency-contacts.json"
    result = ValidationResult("p7-user-operations-drill")
    report = read_json_object(report_path, result, "operations_drill_report")
    if not report:
        return result
    if report.get("schema_version") != "tool-defect-p7-user-operations-drill/v1":
        result.block("operations_drill_schema_invalid")
    if report.get("status") != "PASS":
        result.block(f"operations_drill_not_pass:{report.get('status')}")
    if report.get("source_type") != "REAL_PRODUCTION_EQUIPMENT":
        result.block("operations_drill_source_not_real_equipment")
    if report.get("environment") != "production":
        result.block("operations_drill_environment_not_production")
    if report.get("development_team_executed") is not False:
        result.block("operations_drill_development_team_not_excluded")
    for field in ("drill_id", "coordinator_id"):
        if not _identity(report.get(field)):
            result.block(f"operations_drill_{field}_missing")
    for field in ("started_at", "finished_at"):
        if not valid_iso8601(report.get(field)):
            result.block(f"operations_drill_{field}_invalid")

    _validate_participants(report, result)
    catalog_result = validate_scenario_catalog(repo_root=root)
    catalog_ids = set(catalog_result.checks.get("scenario_ids", []))
    scenario_results = report.get("scenario_results")
    if not isinstance(scenario_results, list):
        result.block("operations_drill_scenario_results_missing")
    else:
        by_id = {
            item.get("scenario_id"): item
            for item in scenario_results
            if isinstance(item, dict) and isinstance(item.get("scenario_id"), str)
        }
        if set(by_id) != catalog_ids or len(by_id) != len(scenario_results):
            result.block("operations_drill_scenario_coverage_invalid")
        for scenario_id, item in by_id.items():
            if item.get("status") != "PASS":
                result.block(f"operations_drill_scenario_not_pass:{scenario_id}")
            if not _identity(item.get("executed_by")):
                result.block(f"operations_drill_executor_missing:{scenario_id}")
            if not valid_iso8601(item.get("started_at")) or not valid_iso8601(item.get("finished_at")):
                result.block(f"operations_drill_time_invalid:{scenario_id}")
            if not _identity(item.get("actual_behavior")):
                result.block(f"operations_drill_actual_behavior_missing:{scenario_id}")
            recovery_time = item.get("recovery_time_seconds")
            if not isinstance(recovery_time, (int, float)) or isinstance(recovery_time, bool) or recovery_time < 0:
                result.block(f"operations_drill_recovery_time_invalid:{scenario_id}")
            if item.get("hold_on_unknown") is not True or item.get("role_separation_verified") is not True:
                result.block(f"operations_drill_safety_control_missing:{scenario_id}")
            verify_file_evidence(
                path_value=item.get("evidence_path"),
                hash_value=item.get("evidence_sha256"),
                base=root,
                result=result,
                label=f"operations_drill_{scenario_id}",
            )
            if scenario_id in HIGH_RISK_SCENARIOS:
                if is_placeholder(item.get("reason")):
                    result.block(f"operations_drill_reason_missing:{scenario_id}")
                if not _identity(item.get("confirmed_by")) or item.get("confirmed_by") == item.get("executed_by"):
                    result.block(f"operations_drill_confirmation_invalid:{scenario_id}")
                if not _identity(item.get("audit_event_id")) or item.get("audit_verified") is not True:
                    result.block(f"operations_drill_audit_invalid:{scenario_id}")
            _validate_special_scenario(scenario_id, item, result)

    bound_contacts = verify_file_evidence(
        path_value=report.get("contacts_path"),
        hash_value=report.get("contacts_sha256"),
        base=root,
        result=result,
        label="operations_drill_contacts",
    )
    if bound_contacts is not None and bound_contacts != expected_contacts.resolve():
        result.block("operations_drill_contacts_wrong_path")
    verify_file_evidence(
        path_value=report.get("raw_log_path"),
        hash_value=report.get("raw_log_sha256"),
        base=root,
        result=result,
        label="operations_drill_raw_log",
    )
    _validate_signoffs(report, result)
    result.checks["report_path"] = str(report_path)
    return result


def validate_p7_06_evidence(*, repo_root: Path | None = None) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    result = ValidationResult("p7-user-operations-readiness")
    result.merge(validate_role_manuals(repo_root=root), "manuals")
    result.merge(validate_scenario_catalog(repo_root=root), "catalog")
    contacts_path = root / "deploy/environments/production/evidence/emergency-contacts.json"
    result.merge(
        validate_emergency_contacts(repo_root=root, contacts_path=contacts_path),
        "contacts",
    )
    result.merge(
        validate_operations_drill(
            repo_root=root,
            contacts_path=contacts_path,
        ),
        "drill",
    )
    result.checks["contract_version"] = "v1"
    return result
