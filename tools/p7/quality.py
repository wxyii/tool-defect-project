"""P7-05 真实质量试运行和模型门槛证据验证。"""

from __future__ import annotations

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


REAL_SOURCES = {"REAL_PRODUCTION", "PRODUCTION_EQUIVALENT"}
REQUIRED_METRICS = {
    "miss_rate": "defect_images",
    "false_pass_rate": "defect_images",
    "override_rate": "total_images",
    "image_quality_failure_rate": "total_images",
    "drift_rate": "total_images",
    "preprocessing_failure_rate": "total_images",
    "paired_disagreement_rate": "total_images",
}
REQUIRED_STRATA = {
    "stations": "stations",
    "shifts": "shifts",
    "batches": "batches",
    "confidence": "confidence_strata",
    "defect_sizes": "defect_sizes",
}
REQUIRED_EVIDENCE = {
    "trial_manifest",
    "ground_truth",
    "raw_log",
    "statistical_analysis",
    "paired_model_results",
}
REQUIRED_SIGNOFF_ROLES = {"QUALITY", "PROCESS", "ALGORITHM", "RELEASE"}


def _identity(value: Any) -> bool:
    return isinstance(value, str) and not is_placeholder(value)


def _number(value: Any, *, positive: bool = False) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return value > 0 if positive else value >= 0


def _unique_scope(values: Any, minimum: int) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized = [value for value in values if isinstance(value, str) and _identity(value)]
    if len(normalized) != len(values) or len(set(normalized)) != len(normalized) or len(normalized) < minimum:
        return []
    return normalized


def _validate_scope(report: dict[str, Any], result: ValidationResult) -> dict[str, list[str]]:
    scope = report.get("trial_scope")
    parsed: dict[str, list[str]] = {}
    if not isinstance(scope, dict):
        result.block("quality_trial_scope_missing")
        return parsed
    minima = {
        "stations": 2,
        "shifts": 2,
        "batches": 2,
        "confidence_strata": 3,
        "defect_sizes": 3,
    }
    for field, minimum in minima.items():
        values = _unique_scope(scope.get(field), minimum)
        if not values:
            result.block(f"quality_scope_{field}_insufficient")
        else:
            parsed[field] = values
    if set(parsed.get("confidence_strata", [])) != {"LOW", "MEDIUM", "HIGH"}:
        result.block("quality_confidence_strata_incomplete")
    if set(parsed.get("defect_sizes", [])) != {"SMALL", "MEDIUM", "LARGE"}:
        result.block("quality_defect_size_strata_incomplete")
    if scope.get("sample_source") not in REAL_SOURCES:
        result.block("quality_sample_source_not_real")
    if scope.get("research_34_used_as_substitute") is not False:
        result.block("quality_research_set_substitution_not_rejected")
    if not _identity(scope.get("sampling_method")):
        result.block("quality_sampling_method_missing")
    if not _identity(scope.get("selection_bias_assessment")):
        result.block("quality_selection_bias_assessment_missing")
    if not isinstance(scope.get("inclusion_criteria"), list) or not scope.get("inclusion_criteria"):
        result.block("quality_inclusion_criteria_missing")
    if not isinstance(scope.get("exclusion_criteria"), list):
        result.block("quality_exclusion_criteria_missing")
    coverage = scope.get("sampling_frame_coverage")
    if not _number(coverage, positive=True) or coverage > 1:
        result.block("quality_sampling_frame_coverage_invalid")
    return parsed


def _validate_denominators(report: dict[str, Any], result: ValidationResult) -> dict[str, int]:
    denominators = report.get("denominators")
    parsed: dict[str, int] = {}
    if not isinstance(denominators, dict):
        result.block("quality_denominators_missing")
        return parsed
    for field in ("total_images", "inspected_images", "defect_images", "nondefect_images", "ground_truth_resolved"):
        value = denominators.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            result.block(f"quality_denominator_invalid:{field}")
        else:
            parsed[field] = value
    total = parsed.get("total_images", 0)
    if total <= 34:
        result.block("quality_total_images_not_larger_than_research_set")
    if parsed.get("inspected_images") != total:
        result.block("quality_inspected_denominator_mismatch")
    if parsed.get("ground_truth_resolved") != total:
        result.block("quality_ground_truth_denominator_mismatch")
    if parsed.get("defect_images", -1) + parsed.get("nondefect_images", -1) != total:
        result.block("quality_class_denominator_mismatch")
    if parsed.get("defect_images", 0) <= 0 or parsed.get("nondefect_images", 0) <= 0:
        result.block("quality_both_classes_required")
    return parsed


def _validate_metrics(
    report: dict[str, Any],
    denominators: dict[str, int],
    result: ValidationResult,
) -> None:
    metrics = report.get("metrics")
    if not isinstance(metrics, dict):
        result.block("quality_metrics_missing")
        return
    for name, denominator_key in REQUIRED_METRICS.items():
        item = metrics.get(name)
        if not isinstance(item, dict):
            result.block(f"quality_metric_missing:{name}")
            continue
        numerator = item.get("numerator")
        denominator = item.get("denominator")
        estimate = item.get("estimate")
        maximum = item.get("maximum_allowed")
        if not isinstance(numerator, int) or isinstance(numerator, bool) or numerator < 0:
            result.block(f"quality_metric_numerator_invalid:{name}")
        if denominator != denominators.get(denominator_key) or not isinstance(denominator, int) or denominator <= 0:
            result.block(f"quality_metric_denominator_invalid:{name}")
        if _number(numerator) and isinstance(denominator, int) and denominator > 0:
            expected = numerator / denominator
            if not _number(estimate) or abs(float(estimate) - expected) > 1e-9:
                result.block(f"quality_metric_estimate_mismatch:{name}")
        if not _number(maximum):
            result.block(f"quality_metric_threshold_invalid:{name}")
        elif _number(estimate) and estimate > maximum:
            result.block(f"quality_metric_threshold_missed:{name}")
        interval = item.get("confidence_interval_95")
        if (
            not isinstance(interval, list)
            or len(interval) != 2
            or not all(_number(value) for value in interval)
            or interval[0] > interval[1]
            or (_number(estimate) and not interval[0] <= estimate <= interval[1])
        ):
            result.block(f"quality_metric_confidence_interval_invalid:{name}")
        if item.get("status") != "PASS":
            result.block(f"quality_metric_not_pass:{name}")


def _validate_strata(
    report: dict[str, Any],
    scope: dict[str, list[str]],
    result: ValidationResult,
) -> None:
    strata = report.get("stratified_results")
    if not isinstance(strata, dict):
        result.block("quality_stratified_results_missing")
        return
    for result_key, scope_key in REQUIRED_STRATA.items():
        items = strata.get(result_key)
        expected = set(scope.get(scope_key, []))
        if not isinstance(items, list):
            result.block(f"quality_stratum_missing:{result_key}")
            continue
        by_value = {
            item.get("value"): item
            for item in items
            if isinstance(item, dict) and isinstance(item.get("value"), str)
        }
        if set(by_value) != expected or len(by_value) != len(items):
            result.block(f"quality_stratum_coverage_invalid:{result_key}")
        for value, item in by_value.items():
            if not isinstance(item.get("denominator"), int) or item.get("denominator", 0) <= 0:
                result.block(f"quality_stratum_denominator_invalid:{result_key}:{value}")
            interval = item.get("confidence_interval_95")
            if not isinstance(interval, list) or len(interval) != 2 or not all(_number(number) for number in interval):
                result.block(f"quality_stratum_ci_invalid:{result_key}:{value}")
            if item.get("status") != "PASS":
                result.block(f"quality_stratum_not_pass:{result_key}:{value}")


def _validate_paired_models(
    report: dict[str, Any],
    denominators: dict[str, int],
    result: ValidationResult,
) -> None:
    paired = report.get("paired_model_comparison")
    if not isinstance(paired, dict):
        result.block("quality_paired_model_comparison_missing")
        return
    old_id = paired.get("stable_model_version_id")
    new_id = paired.get("candidate_model_version_id")
    if not _identity(old_id) or not _identity(new_id) or old_id == new_id:
        result.block("quality_paired_model_identity_invalid")
    old_hash = paired.get("stable_package_sha256")
    new_hash = paired.get("candidate_package_sha256")
    if (
        not isinstance(old_hash, str)
        or SHA256.fullmatch(old_hash) is None
        or not isinstance(new_hash, str)
        or SHA256.fullmatch(new_hash) is None
        or old_hash == new_hash
    ):
        result.block("quality_paired_model_hash_invalid")
    if paired.get("paired_samples") != denominators.get("total_images"):
        result.block("quality_paired_sample_denominator_mismatch")
    if paired.get("method") not in {"MCNEMAR", "PAIRED_BOOTSTRAP", "MCNEMAR_AND_PAIRED_BOOTSTRAP"}:
        result.block("quality_paired_method_invalid")
    p_value = paired.get("p_value")
    if not _number(p_value) or p_value > 1:
        result.block("quality_paired_p_value_invalid")
    if paired.get("candidate_not_worse") is not True or paired.get("status") != "PASS":
        result.block("quality_paired_model_gate_not_pass")


def _validate_evidence(report: dict[str, Any], root: Path, result: ValidationResult) -> None:
    evidence = report.get("evidence")
    if not isinstance(evidence, dict):
        result.block("quality_evidence_missing")
        return
    for name in sorted(REQUIRED_EVIDENCE):
        item = evidence.get(name)
        if not isinstance(item, dict):
            result.block(f"quality_evidence_item_missing:{name}")
            continue
        verify_file_evidence(
            path_value=item.get("path"),
            hash_value=item.get("sha256"),
            base=root,
            result=result,
            label=f"quality_{name}",
        )


def _validate_signoffs(report: dict[str, Any], result: ValidationResult) -> None:
    signoffs = report.get("sign_offs")
    if not isinstance(signoffs, list):
        result.block("quality_signoffs_missing")
        return
    by_role = {
        item.get("role"): item
        for item in signoffs
        if isinstance(item, dict) and isinstance(item.get("role"), str)
    }
    if set(by_role) != REQUIRED_SIGNOFF_ROLES or len(by_role) != len(signoffs):
        result.block("quality_signoff_roles_invalid")
    actors: list[str] = []
    for role in sorted(REQUIRED_SIGNOFF_ROLES):
        item = by_role.get(role)
        if not isinstance(item, dict):
            continue
        if item.get("decision") != "APPROVED":
            result.block(f"quality_signoff_not_approved:{role}")
        actor = item.get("actor_id")
        if not _identity(actor):
            result.block(f"quality_signoff_actor_missing:{role}")
        else:
            actors.append(actor)
        if not valid_iso8601(item.get("signed_at")):
            result.block(f"quality_signoff_time_invalid:{role}")
        if is_placeholder(item.get("reason")):
            result.block(f"quality_signoff_reason_missing:{role}")
    if len(set(actors)) != len(REQUIRED_SIGNOFF_ROLES):
        result.block("quality_signoff_actors_not_distinct")


def validate_quality_trial_report(
    *,
    repo_root: Path | None = None,
    report_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    report_path = report_path or root / "deploy/environments/production/evidence/quality-trial-report.json"
    result = ValidationResult("p7-quality-trial")
    report = read_json_object(report_path, result, "quality_trial_report")
    if not report:
        return result
    if report.get("schema_version") != "tool-defect-quality-trial/v1":
        result.block("quality_schema_invalid")
    if report.get("status") != "PASS":
        result.block(f"quality_status_not_pass:{report.get('status')}")
    if report.get("source_type") not in REAL_SOURCES:
        result.block("quality_source_not_real")
    if report.get("environment") != "production":
        result.block("quality_environment_not_production")
    if report.get("contract_version") != "v1":
        result.block("quality_contract_version_invalid")
    for field in ("trial_id", "executor_id"):
        if not _identity(report.get(field)):
            result.block(f"quality_{field}_missing")
    for field in ("started_at", "finished_at"):
        if not valid_iso8601(report.get(field)):
            result.block(f"quality_{field}_invalid")

    scope = _validate_scope(report, result)
    denominators = _validate_denominators(report, result)
    _validate_metrics(report, denominators, result)
    _validate_strata(report, scope, result)
    _validate_paired_models(report, denominators, result)
    _validate_evidence(report, root, result)
    model_gate = report.get("model_gate")
    if not isinstance(model_gate, dict) or model_gate.get("status") != "PASS":
        result.block("quality_model_gate_not_pass")
    else:
        if not _identity(model_gate.get("threshold_version")):
            result.block("quality_model_gate_threshold_version_missing")
        if model_gate.get("recommendation") != "APPROVE":
            result.block("quality_model_gate_recommendation_not_approve")
    _validate_signoffs(report, result)
    result.checks["report_path"] = str(report_path)
    result.checks["contract_version"] = "v1"
    return result
