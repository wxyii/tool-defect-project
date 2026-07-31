"""P7-04 真实生产非功能验收证据验证。"""

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


REAL_SOURCES = {"REAL_PRODUCTION", "PRODUCTION_EQUIVALENT"}
REQUIRED_TEST_RUNS = {
    "faults": "make test-faults",
    "security": "make test-security",
    "performance": "make test-performance",
}
REQUIRED_THRESHOLDS = {
    "cycle_time_ms",
    "allowed_latency_ms",
    "sustained_duration_seconds",
    "max_offline_hours",
    "rpo_seconds",
    "rto_seconds",
    "concurrent_reviews",
    "capacity_bytes",
}
REQUIRED_FAULT_SCENARIOS = {
    "network_partition",
    "database_failover",
    "object_storage_outage",
    "broker_restart",
    "inference_crash",
    "edge_power_loss",
    "clock_skew",
    "disk_watermark",
    "long_stability",
}
REQUIRED_SECURITY_CONTROLS = {
    "mtls",
    "certificate_revocation",
    "certificate_rotation",
    "oidc_authentication",
    "rbac_denial",
    "secret_injection",
    "image_and_model_signatures",
    "network_isolation",
    "audit_integrity",
    "backup_access_control",
}
REQUIRED_SIGNOFF_ROLES = {"QUALITY", "OPERATIONS", "SECURITY", "INFRASTRUCTURE"}


def _number(value: Any, *, positive: bool = False) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return value > 0 if positive else value >= 0


def _identity(value: Any) -> bool:
    return isinstance(value, str) and not is_placeholder(value)


def _validate_test_runs(report: dict[str, Any], root: Path, result: ValidationResult) -> None:
    runs = report.get("test_runs")
    if not isinstance(runs, dict):
        result.block("nonfunctional_test_runs_missing")
        return
    for name, command in REQUIRED_TEST_RUNS.items():
        run = runs.get(name)
        if not isinstance(run, dict):
            result.block(f"nonfunctional_test_run_missing:{name}")
            continue
        if run.get("command") != command:
            result.block(f"nonfunctional_test_command_invalid:{name}")
        if run.get("status") != "PASS" or run.get("exit_code") != 0:
            result.block(f"nonfunctional_test_run_not_pass:{name}")
        if run.get("skipped") != 0:
            result.block(f"nonfunctional_test_run_has_skips:{name}")
        if not isinstance(run.get("total"), int) or isinstance(run.get("total"), bool) or run.get("total", 0) < 1:
            result.block(f"nonfunctional_test_total_invalid:{name}")
        if run.get("simulator_only") is not False:
            result.block(f"nonfunctional_test_simulator_only_not_false:{name}")
        if run.get("source_type") not in REAL_SOURCES:
            result.block(f"nonfunctional_test_source_not_real:{name}")
        verify_file_evidence(
            path_value=run.get("raw_log_path"),
            hash_value=run.get("raw_log_sha256"),
            base=root,
            result=result,
            label=f"nonfunctional_{name}_raw_log",
        )


def _validate_thresholds(report: dict[str, Any], result: ValidationResult) -> dict[str, float]:
    thresholds = report.get("signed_thresholds")
    values: dict[str, float] = {}
    if not isinstance(thresholds, dict):
        result.block("nonfunctional_signed_thresholds_missing")
        return values
    for name in sorted(REQUIRED_THRESHOLDS):
        item = thresholds.get(name)
        if not isinstance(item, dict):
            result.block(f"nonfunctional_threshold_missing:{name}")
            continue
        value = item.get("value")
        if not _number(value, positive=True):
            result.block(f"nonfunctional_threshold_value_invalid:{name}")
        else:
            values[name] = float(value)
        if item.get("status") != "CONFIRMED":
            result.block(f"nonfunctional_threshold_not_confirmed:{name}")
        if not _identity(item.get("decision_id")):
            result.block(f"nonfunctional_threshold_decision_missing:{name}")
        if not _identity(item.get("approved_by")):
            result.block(f"nonfunctional_threshold_approver_missing:{name}")
        if not valid_iso8601(item.get("approved_at")):
            result.block(f"nonfunctional_threshold_approved_at_invalid:{name}")
    return values


def _validate_performance(
    report: dict[str, Any],
    thresholds: dict[str, float],
    result: ValidationResult,
) -> None:
    performance = report.get("performance")
    if not isinstance(performance, dict):
        result.block("nonfunctional_performance_missing")
        return
    p95 = performance.get("end_to_end_p95_ms")
    if not _number(p95, positive=True):
        result.block("nonfunctional_latency_p95_invalid")
    elif "allowed_latency_ms" in thresholds and p95 > thresholds["allowed_latency_ms"]:
        result.block("nonfunctional_latency_target_missed")
    cycle = thresholds.get("cycle_time_ms")
    margin = performance.get("cycle_margin_ms")
    if cycle is not None and _number(p95, positive=True):
        expected_margin = cycle - float(p95)
        if not _number(margin, positive=True) or abs(float(margin) - expected_margin) > 0.001:
            result.block("nonfunctional_cycle_margin_invalid")
    if not _number(performance.get("throughput_per_second"), positive=True):
        result.block("nonfunctional_throughput_invalid")
    duration = performance.get("sustained_duration_seconds")
    if not _number(duration, positive=True) or (
        "sustained_duration_seconds" in thresholds
        and duration < thresholds["sustained_duration_seconds"]
    ):
        result.block("nonfunctional_sustained_duration_insufficient")
    concurrency = performance.get("concurrent_reviews")
    if not _number(concurrency, positive=True) or (
        "concurrent_reviews" in thresholds and concurrency < thresholds["concurrent_reviews"]
    ):
        result.block("nonfunctional_concurrent_reviews_insufficient")
    capacity = performance.get("capacity_bytes_tested")
    if not _number(capacity, positive=True) or (
        "capacity_bytes" in thresholds and capacity < thresholds["capacity_bytes"]
    ):
        result.block("nonfunctional_capacity_insufficient")
    if performance.get("failures") != 0:
        result.block("nonfunctional_performance_failures_present")
    if performance.get("original_images_lost") != 0:
        result.block("nonfunctional_original_image_loss")
    actual_rpo = performance.get("rpo_actual_seconds")
    actual_rto = performance.get("rto_actual_seconds")
    if not _number(actual_rpo) or (
        "rpo_seconds" in thresholds and actual_rpo > thresholds["rpo_seconds"]
    ):
        result.block("nonfunctional_rpo_target_missed")
    if not _number(actual_rto) or (
        "rto_seconds" in thresholds and actual_rto > thresholds["rto_seconds"]
    ):
        result.block("nonfunctional_rto_target_missed")


def _validate_fault_scenarios(report: dict[str, Any], root: Path, result: ValidationResult) -> None:
    scenarios = report.get("fault_scenarios")
    if not isinstance(scenarios, list):
        result.block("nonfunctional_fault_scenarios_missing")
        return
    by_name = {
        item.get("name"): item
        for item in scenarios
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if len(by_name) != len(scenarios):
        result.block("nonfunctional_fault_scenario_duplicate_or_invalid")
    missing = sorted(REQUIRED_FAULT_SCENARIOS.difference(by_name))
    if missing:
        result.block(f"nonfunctional_fault_scenarios_missing:{','.join(missing)}")
    for name in sorted(REQUIRED_FAULT_SCENARIOS):
        item = by_name.get(name)
        if not isinstance(item, dict):
            continue
        if item.get("status") != "PASS":
            result.block(f"nonfunctional_fault_not_pass:{name}")
        if item.get("real_fault_injection") is not True:
            result.block(f"nonfunctional_fault_not_real:{name}")
        if item.get("critical_data_loss") != 0:
            result.block(f"nonfunctional_fault_data_loss:{name}")
        if item.get("unreconciled_duplicates") != 0:
            result.block(f"nonfunctional_fault_duplicates:{name}")
        if item.get("hold_on_unknown") is not True:
            result.block(f"nonfunctional_fault_unknown_not_hold:{name}")
        verify_file_evidence(
            path_value=item.get("evidence_path"),
            hash_value=item.get("evidence_sha256"),
            base=root,
            result=result,
            label=f"nonfunctional_fault_{name}",
        )


def _validate_security(report: dict[str, Any], root: Path, result: ValidationResult) -> None:
    controls = report.get("security_controls")
    if not isinstance(controls, list):
        result.block("nonfunctional_security_controls_missing")
        return
    by_name = {
        item.get("name"): item
        for item in controls
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if len(by_name) != len(controls):
        result.block("nonfunctional_security_control_duplicate_or_invalid")
    missing = sorted(REQUIRED_SECURITY_CONTROLS.difference(by_name))
    if missing:
        result.block(f"nonfunctional_security_controls_missing:{','.join(missing)}")
    for name in sorted(REQUIRED_SECURITY_CONTROLS):
        item = by_name.get(name)
        if not isinstance(item, dict):
            continue
        if item.get("status") != "PASS":
            result.block(f"nonfunctional_security_not_pass:{name}")
        if item.get("real_probe") is not True:
            result.block(f"nonfunctional_security_not_real_probe:{name}")
        if item.get("critical_findings") != 0:
            result.block(f"nonfunctional_security_critical_findings:{name}")
        verify_file_evidence(
            path_value=item.get("evidence_path"),
            hash_value=item.get("evidence_sha256"),
            base=root,
            result=result,
            label=f"nonfunctional_security_{name}",
        )


def _validate_alerts(report: dict[str, Any], result: ValidationResult) -> None:
    alerts = report.get("critical_alerts")
    if not isinstance(alerts, list) or not alerts:
        result.block("nonfunctional_critical_alerts_missing")
        return
    identifiers: set[str] = set()
    for item in alerts:
        if not isinstance(item, dict) or not _identity(item.get("alert_id")):
            result.block("nonfunctional_critical_alert_invalid")
            continue
        alert_id = item["alert_id"]
        if alert_id in identifiers:
            result.block(f"nonfunctional_critical_alert_duplicate:{alert_id}")
        identifiers.add(alert_id)
        if item.get("triggered") is not True or item.get("recovered") is not True:
            result.block(f"nonfunctional_critical_alert_not_exercised:{alert_id}")


def _validate_signoffs(report: dict[str, Any], result: ValidationResult) -> None:
    signoffs = report.get("sign_offs")
    if not isinstance(signoffs, list):
        result.block("nonfunctional_signoffs_missing")
        return
    by_role = {
        item.get("role"): item
        for item in signoffs
        if isinstance(item, dict) and isinstance(item.get("role"), str)
    }
    if set(by_role) != REQUIRED_SIGNOFF_ROLES:
        result.block("nonfunctional_signoff_roles_invalid")
    actors: list[str] = []
    for role in sorted(REQUIRED_SIGNOFF_ROLES):
        item = by_role.get(role)
        if not isinstance(item, dict):
            continue
        if item.get("decision") != "APPROVED":
            result.block(f"nonfunctional_signoff_not_approved:{role}")
        actor = item.get("actor_id")
        if not _identity(actor):
            result.block(f"nonfunctional_signoff_actor_missing:{role}")
        else:
            actors.append(actor)
        if not valid_iso8601(item.get("signed_at")):
            result.block(f"nonfunctional_signoff_time_invalid:{role}")
        if is_placeholder(item.get("reason")):
            result.block(f"nonfunctional_signoff_reason_missing:{role}")
    if len(set(actors)) != len(REQUIRED_SIGNOFF_ROLES):
        result.block("nonfunctional_signoff_actors_not_distinct")


def validate_nonfunctional_report(
    *,
    repo_root: Path | None = None,
    report_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    report_path = report_path or root / "deploy/environments/production/evidence/non-functional-acceptance.json"
    result = ValidationResult("p7-non-functional-acceptance")
    report = read_json_object(report_path, result, "nonfunctional_report")
    if not report:
        return result
    if report.get("schema_version") != "tool-defect-non-functional-acceptance/v1":
        result.block("nonfunctional_schema_invalid")
    if report.get("status") != "PASS":
        result.block(f"nonfunctional_status_not_pass:{report.get('status')}")
    if report.get("source_type") not in REAL_SOURCES:
        result.block("nonfunctional_source_not_real")
    if report.get("environment") != "production":
        result.block("nonfunctional_environment_not_production")
    if report.get("contract_version") != "v1":
        result.block("nonfunctional_contract_version_invalid")
    for field in ("run_id", "executor_id", "host_id"):
        if not _identity(report.get(field)):
            result.block(f"nonfunctional_{field}_missing")
    for field in ("started_at", "finished_at"):
        if not valid_iso8601(report.get(field)):
            result.block(f"nonfunctional_{field}_invalid")

    verify_file_evidence(
        path_value=report.get("site_config_path"),
        hash_value=report.get("site_config_sha256"),
        base=root,
        result=result,
        label="nonfunctional_site_config",
    )
    verify_file_evidence(
        path_value=report.get("threshold_approval_path"),
        hash_value=report.get("threshold_approval_sha256"),
        base=root,
        result=result,
        label="nonfunctional_threshold_approval",
    )
    _validate_test_runs(report, root, result)
    thresholds = _validate_thresholds(report, result)
    _validate_performance(report, thresholds, result)
    _validate_fault_scenarios(report, root, result)
    _validate_security(report, root, result)
    _validate_alerts(report, result)
    _validate_signoffs(report, result)
    result.checks["report_path"] = str(report_path)
    result.checks["contract_version"] = "v1"
    return result
