"""P7-01 生产决策、环境、模型和起飞前证据的严格验证。"""

from __future__ import annotations

from collections import Counter
from importlib import util as importlib_util
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from tools.p7.common import (
    PLACEHOLDER,
    SHA256,
    ValidationResult,
    get_dotted,
    is_placeholder,
    read_env_file,
    read_json_object,
    read_simple_yaml_mapping,
    repository_root,
    valid_iso8601,
    verify_file_evidence,
)


ALLOWED_CLOSURE_STATUSES = {
    "PENDING_SITE_SIGNOFF",
    "CONFIRMED",
    "CONFIRMED_DEFAULT",
    "DEFERRED",
}
TECHNOLOGY_DECISION_IDS = {
    "DEC-CAPTURE-PLC-001",
    "DEC-CAPTURE-CAMERA-001",
    "DEC-EDGE-OS-001",
    "DEC-IDENTITY-001",
    "DEC-STORAGE-PRODUCT-001",
    "DEC-MESSAGING-001",
    "DEC-MONITORING-001",
    "DEC-COMPUTE-001",
    "DEC-DEPLOYMENT-001",
}
REQUIRED_IMAGE_NAMES = (
    "GATEWAY",
    "BUSINESS",
    "INFERENCE",
    "POSTGRES",
    "RABBITMQ",
    "OBJECT_STORAGE",
    "TELEMETRY",
)
SECRET_KEY = re.compile(
    r"(?:PASSWORD|PASSWD|SECRET|TOKEN|PRIVATE_KEY|ACCESS_KEY|CLIENT_SECRET|CREDENTIAL)",
    re.IGNORECASE,
)
ALLOWED_REAL_SOURCES = {"REAL_SITE", "REAL_PRODUCTION", "PRODUCTION_EQUIVALENT"}


def _items_by_id(
    value: Any,
    result: ValidationResult,
    label: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        result.error(f"{label}_not_array")
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            result.error(f"{label}_item_not_object:{index}")
            continue
        identifier = item.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            result.error(f"{label}_id_missing:{index}")
            continue
        if identifier in indexed:
            result.error(f"{label}_id_duplicate:{identifier}")
            continue
        indexed[identifier] = item
    return indexed


def _validate_approval(
    approval: Any,
    *,
    result: ValidationResult,
    label: str,
    evidence_base: Path,
) -> None:
    if not isinstance(approval, dict):
        result.block(f"{label}_approval_missing")
        return
    for field in ("approver_id", "role", "approved_at"):
        if is_placeholder(approval.get(field)):
            result.block(f"{label}_approval_{field}_missing")
    if not valid_iso8601(approval.get("approved_at")):
        result.block(f"{label}_approval_time_invalid")
    verify_file_evidence(
        path_value=approval.get("evidence_path"),
        hash_value=approval.get("evidence_sha256"),
        base=evidence_base,
        result=result,
        label=f"{label}_approval",
    )


def _validate_technology_inventory(
    path: Path,
    *,
    result: ValidationResult,
    repo_root: Path,
) -> None:
    inventory = read_json_object(path, result, "technology_inventory")
    if not inventory:
        return
    if inventory.get("schema_version") != "tool-defect-technology-inventory/v1":
        result.block("technology_inventory_schema_invalid")
    if inventory.get("status") != "APPROVED":
        result.block("technology_inventory_not_approved")
    if inventory.get("source_type") not in ALLOWED_REAL_SOURCES:
        result.block("technology_inventory_not_real_site")
    if not valid_iso8601(inventory.get("generated_at")):
        result.block("technology_inventory_generated_at_invalid")
    items = _items_by_id(inventory.get("items"), result, "technology_inventory_items")
    missing = sorted(TECHNOLOGY_DECISION_IDS.difference(items))
    result.blockers.extend(
        f"technology_inventory_decision_missing:{identifier}"
        for identifier in missing
        if f"technology_inventory_decision_missing:{identifier}" not in result.blockers
    )
    for identifier in sorted(TECHNOLOGY_DECISION_IDS.intersection(items)):
        item = items[identifier]
        prefix = f"technology_inventory:{identifier}"
        for field in (
            "component",
            "product",
            "exact_version",
            "license",
            "support_end",
        ):
            if is_placeholder(item.get(field)):
                result.block(f"{prefix}_{field}_missing")
        if not valid_iso8601(item.get("support_end")):
            result.block(f"{prefix}_support_end_invalid")
        artifact_hash = item.get("artifact_sha256")
        if not isinstance(artifact_hash, str) or SHA256.fullmatch(artifact_hash) is None:
            result.block(f"{prefix}_artifact_sha256_invalid")
        verify_file_evidence(
            path_value=item.get("sbom_path"),
            hash_value=item.get("sbom_sha256"),
            base=repo_root,
            result=result,
            label=f"{prefix}_sbom",
        )
        verify_file_evidence(
            path_value=item.get("license_evidence_path"),
            hash_value=item.get("license_evidence_sha256"),
            base=repo_root,
            result=result,
            label=f"{prefix}_license",
        )
        _validate_approval(
            item.get("approval"),
            result=result,
            label=prefix,
            evidence_base=repo_root,
        )


def validate_config(
    *,
    repo_root: Path | None = None,
    registry_path: Path | None = None,
    closure_path: Path | None = None,
    site_config_path: Path | None = None,
    inventory_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    registry_path = registry_path or root / "Docs/decisions/site-parameter-decisions.json"
    closure_path = closure_path or root / "Docs/decisions/production-decision-closure.json"
    site_config_path = site_config_path or root / "deploy/environments/production/site-config.yaml"
    inventory_path = inventory_path or root / "deploy/environments/production/evidence/technology-inventory.json"
    result = ValidationResult("p7-production-config")

    registry = read_json_object(registry_path, result, "decision_registry")
    closure = read_json_object(closure_path, result, "decision_closure")
    site_config = read_simple_yaml_mapping(site_config_path, result, "site_config")
    if not registry or not closure or not site_config:
        return result

    registry_items = _items_by_id(registry.get("decisions"), result, "registry_decisions")
    closure_items = _items_by_id(closure.get("decisions"), result, "closure_decisions")
    if set(registry_items) != set(closure_items):
        for identifier in sorted(set(registry_items).difference(closure_items)):
            result.block(f"closure_decision_missing:{identifier}")
        for identifier in sorted(set(closure_items).difference(registry_items)):
            result.error(f"closure_decision_unknown:{identifier}")

    status_counts: Counter[str] = Counter()
    for identifier in sorted(set(registry_items).intersection(closure_items)):
        registered = registry_items[identifier]
        closed = closure_items[identifier]
        status = closed.get("closure_status")
        if status not in ALLOWED_CLOSURE_STATUSES:
            result.error(f"closure_status_invalid:{identifier}:{status}")
            continue
        status_counts[str(status)] += 1
        registered_status = registered.get("status")
        allowed: set[str]
        if registered_status in {"上线阻断", "已确认"}:
            allowed = {"CONFIRMED"}
        elif registered_status == "暂定默认值":
            allowed = {"CONFIRMED", "CONFIRMED_DEFAULT"}
        elif registered_status == "可后置":
            allowed = {"CONFIRMED", "DEFERRED"}
        else:
            result.error(f"registry_status_invalid:{identifier}:{registered_status}")
            continue
        if status not in allowed:
            result.block(f"decision_not_closed:{identifier}:{status}")
        if is_placeholder(closed.get("closure_evidence")):
            result.block(f"closure_evidence_missing:{identifier}")
        if status == "CONFIRMED":
            _validate_approval(
                closed.get("approval"),
                result=result,
                label=f"decision:{identifier}",
                evidence_base=root,
            )

        config_keys = registered.get("config_keys")
        if not isinstance(config_keys, list) or not config_keys:
            result.error(f"decision_config_keys_invalid:{identifier}")
            continue
        for dotted_key in config_keys:
            if not isinstance(dotted_key, str):
                result.error(f"decision_config_key_not_string:{identifier}")
                continue
            exists, value = get_dotted(site_config, dotted_key)
            if not exists:
                result.error(f"site_config_key_missing:{identifier}:{dotted_key}")
            elif is_placeholder(value):
                result.block(f"site_config_value_pending:{identifier}:{dotted_key}")

    summary = closure.get("summary")
    expected_summary = {
        "total_decisions": len(closure_items),
        "pending_site_signoff": status_counts["PENDING_SITE_SIGNOFF"],
        "confirmed": status_counts["CONFIRMED"],
        "confirmed_default": status_counts["CONFIRMED_DEFAULT"],
        "deferred": status_counts["DEFERRED"],
    }
    if summary != expected_summary:
        result.error("decision_closure_summary_mismatch")
    if not valid_iso8601(closure.get("closure_date")):
        result.block("decision_closure_date_pending")
    if is_placeholder(closure.get("closure_authority")):
        result.block("decision_closure_authority_missing")
    if is_placeholder(site_config.get("site_config_version")):
        result.block("site_config_version_pending")
    if not valid_iso8601(site_config.get("deployed_at")):
        result.block("site_config_deployed_at_pending")

    safety_expectations = {
        "offline.delete_unsynchronized_images": False,
        "disposition.unknown_threshold_action": "HOLD",
        "disposition.technical_failure_action": "HOLD",
        "storage.public_access_enabled": False,
    }
    for dotted_key, expected in safety_expectations.items():
        exists, actual = get_dotted(site_config, dotted_key)
        if exists and not is_placeholder(actual) and actual != expected:
            result.error(f"unsafe_site_config:{dotted_key}:{actual!r}")
    exists, protocol = get_dotted(site_config, "storage.protocol")
    if exists and not is_placeholder(protocol) and protocol != "S3_COMPATIBLE":
        result.error(f"storage_protocol_invalid:{protocol!r}")
    watermarks: list[int] = []
    for dotted_key in (
        "capacity.disk_warning_percent",
        "capacity.disk_critical_percent",
        "capacity.disk_pause_percent",
    ):
        exists, value = get_dotted(site_config, dotted_key)
        if exists and isinstance(value, int) and not isinstance(value, bool):
            watermarks.append(value)
    if len(watermarks) == 3 and not (0 < watermarks[0] < watermarks[1] < watermarks[2] <= 100):
        result.error("disk_watermarks_not_strictly_increasing")

    _validate_technology_inventory(inventory_path, result=result, repo_root=root)
    result.checks.update(
        {
            "registered_decisions": len(registry_items),
            "closure_decisions": len(closure_items),
            "closure_status_counts": dict(sorted(status_counts.items())),
            "technology_decisions_required": len(TECHNOLOGY_DECISION_IDS),
        }
    )
    return result


def validate_env(
    *,
    repo_root: Path | None = None,
    env_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    env_path = env_path or root / "deploy/environments/production/.env"
    result = ValidationResult("p7-production-env")
    values = read_env_file(env_path, result, "production_env")
    if not values:
        return result
    if ".template" in env_path.name.lower():
        result.block("production_env_is_template")

    required = ["TD_RELEASE_ID", "TD_ENVIRONMENT", "COMPOSE_PROJECT_NAME"]
    for image_name in REQUIRED_IMAGE_NAMES:
        required.extend(
            (
                f"TD_{image_name}_IMAGE_REPOSITORY",
                f"TD_{image_name}_IMAGE_DIGEST",
            )
        )
    for key in required:
        if key not in values or is_placeholder(values.get(key)):
            result.block(f"production_env_value_missing:{key}")
    if values.get("TD_ENVIRONMENT") != "production":
        result.error("production_env_environment_not_production")
    release_id = values.get("TD_RELEASE_ID", "")
    if release_id.lower() in {"latest", "current", "main", "master"}:
        result.error("production_release_id_mutable")
    for image_name in REQUIRED_IMAGE_NAMES:
        repository = values.get(f"TD_{image_name}_IMAGE_REPOSITORY", "")
        digest = values.get(f"TD_{image_name}_IMAGE_DIGEST", "")
        if repository and ("@" in repository or any(character.isspace() for character in repository)):
            result.error(f"image_repository_invalid:{image_name}")
        if digest and SHA256.fullmatch(digest) is None:
            result.error(f"image_digest_invalid:{image_name}")

    for key, value in values.items():
        if SECRET_KEY.search(key) and value and not value.startswith(("${", "/run/secrets/")):
            result.error(f"plaintext_secret_forbidden:{key}")
        if "." in key:
            result.block(f"unconsumed_site_parameter_in_env:{key}")
    result.checks.update(
        {
            "path": str(env_path),
            "required_values": len(required),
            "configured_values": sum(1 for key in required if values.get(key)),
        }
    )
    return result


def validate_model_package(
    *,
    repo_root: Path | None = None,
    package_dir: Path | None = None,
    trusted_keys_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    result = ValidationResult("p7-production-model-package")
    if package_dir is None:
        configured = os.environ.get("TD_MODEL_EVIDENCE_DIR")
        package_dir = Path(configured) if configured else None
    if trusted_keys_path is None:
        configured = os.environ.get("TD_MODEL_TRUST_ROOT")
        trusted_keys_path = Path(configured) if configured else None
    if package_dir is None or not package_dir.is_dir():
        result.block("production_model_evidence_dir_missing")
        return result
    if trusted_keys_path is None or not trusted_keys_path.is_file():
        result.block("production_model_trust_roots_missing")
        return result

    verifier_path = root / "jobs/model-evaluator/verify_p6_05.py"
    if not verifier_path.is_file():
        result.error("p6_model_verifier_missing")
        return result
    try:
        spec = importlib_util.spec_from_file_location("tool_defect_verify_p6_05", verifier_path)
        if spec is None or spec.loader is None:
            raise ImportError("无法创建 P6-05 验证器加载规格")
        module = importlib_util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        report = module.verify_package(package_dir.resolve(), trusted_keys_path.resolve())
    except Exception as exc:
        result.error(f"production_model_verifier_failed:{type(exc).__name__}")
        return result
    result.checks["p6_supply_chain_report"] = report
    if report.get("status") not in {"PASS", "VERIFIED", "COMPLETE"}:
        for message in report.get("errors", [])[:100]:
            result.block(f"production_model:{message}")
        if not report.get("errors"):
            result.block(f"production_model_status_invalid:{report.get('status')}")
    return result


def validate_smoke_evidence(
    *,
    repo_root: Path | None = None,
    evidence_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    if evidence_path is None:
        configured = os.environ.get("TD_MODEL_SMOKE_EVIDENCE")
        evidence_path = Path(configured) if configured else root / "deploy/environments/production/evidence/model-smoke-test.json"
    result = ValidationResult("p7-production-model-smoke")
    evidence = read_json_object(evidence_path, result, "model_smoke_evidence")
    if not evidence:
        return result
    if evidence.get("schema_version") != "tool-defect-model-smoke/v1":
        result.block("model_smoke_schema_invalid")
    if evidence.get("status") != "PASS":
        result.block(f"model_smoke_not_pass:{evidence.get('status')}")
    if evidence.get("source_type") not in ALLOWED_REAL_SOURCES:
        result.block("model_smoke_not_real_infrastructure")
    if evidence.get("environment") != "production":
        result.block("model_smoke_environment_not_production")
    for field in ("started_at", "finished_at"):
        if not valid_iso8601(evidence.get(field)):
            result.block(f"model_smoke_{field}_invalid")
    for field in (
        "model_version_id",
        "endpoint",
        "executor_id",
        "host_id",
    ):
        if is_placeholder(evidence.get(field)):
            result.block(f"model_smoke_{field}_missing")
    endpoint = evidence.get("endpoint")
    if isinstance(endpoint, str) and not endpoint.startswith("https://"):
        result.error("model_smoke_endpoint_not_https")
    for field in (
        "model_package_sha256",
        "probe_input_sha256",
        "output_schema_sha256",
    ):
        value = evidence.get(field)
        if not isinstance(value, str) or SHA256.fullmatch(value) is None:
            result.block(f"model_smoke_{field}_invalid")
    if evidence.get("loaded_package_verified") is not True:
        result.block("model_smoke_loaded_package_not_verified")
    if evidence.get("warmup_completed") is not True:
        result.block("model_smoke_warmup_not_completed")
    probe_count = evidence.get("probe_count")
    failure_count = evidence.get("failure_count")
    if not isinstance(probe_count, int) or isinstance(probe_count, bool) or probe_count < 1:
        result.block("model_smoke_probe_count_invalid")
    if failure_count != 0:
        result.block("model_smoke_failures_present")
    verify_file_evidence(
        path_value=evidence.get("raw_log_path"),
        hash_value=evidence.get("raw_log_sha256"),
        base=root,
        result=result,
        label="model_smoke_raw_log",
    )
    result.checks["evidence_path"] = str(evidence_path)
    return result


def validate_preflight_results(
    *,
    repo_root: Path | None = None,
    checklist_path: Path | None = None,
    results_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    checklist_path = checklist_path or root / "deploy/environments/production/checklists/pre-flight.json"
    if results_path is None:
        configured = os.environ.get("TD_PREFLIGHT_RESULTS")
        results_path = Path(configured) if configured else root / "deploy/environments/production/evidence/preflight-results.json"
    result = ValidationResult("p7-production-preflight-results")
    checklist = read_json_object(checklist_path, result, "preflight_checklist")
    results = read_json_object(results_path, result, "preflight_results")
    if not checklist or not results:
        return result
    checklist_items = _items_by_id(checklist.get("items"), result, "preflight_checklist_items")
    result_items = _items_by_id(results.get("items"), result, "preflight_result_items")
    required_ids = {
        identifier
        for identifier, item in checklist_items.items()
        if item.get("required") is True
    }
    if results.get("schema_version") != "tool-defect-preflight-results/v1":
        result.block("preflight_results_schema_invalid")
    if results.get("status") != "PASS":
        result.block(f"preflight_results_not_pass:{results.get('status')}")
    if results.get("source_type") not in ALLOWED_REAL_SOURCES:
        result.block("preflight_results_not_real_site")
    if results.get("environment") != "production":
        result.block("preflight_results_environment_not_production")
    for field in ("started_at", "finished_at"):
        if not valid_iso8601(results.get(field)):
            result.block(f"preflight_results_{field}_invalid")
    for field in ("executor_id", "host_id", "site_config_sha256", "release_id"):
        if is_placeholder(results.get(field)):
            result.block(f"preflight_results_{field}_missing")
    site_config_hash = results.get("site_config_sha256")
    if isinstance(site_config_hash, str) and SHA256.fullmatch(site_config_hash) is None:
        result.block("preflight_results_site_config_sha256_invalid")
    for identifier in sorted(required_ids):
        item = result_items.get(identifier)
        if item is None:
            result.block(f"preflight_required_result_missing:{identifier}")
            continue
        if item.get("status") != "PASS":
            result.block(f"preflight_required_result_not_pass:{identifier}:{item.get('status')}")
        if item.get("exit_code") != 0:
            result.block(f"preflight_required_exit_nonzero:{identifier}")
        command_template = checklist_items[identifier].get("verification_command")
        if item.get("command_template") != command_template:
            result.block(f"preflight_command_template_mismatch:{identifier}")
        executed_command = item.get("verification_command")
        if is_placeholder(executed_command) or (
            isinstance(executed_command, str) and "..." in executed_command
        ):
            result.block(f"preflight_executed_command_unresolved:{identifier}")
        for field in ("executed_at", "executor_id", "host_id", "actual_result"):
            if is_placeholder(item.get(field)):
                result.block(f"preflight_result_field_missing:{identifier}:{field}")
        if not valid_iso8601(item.get("executed_at")):
            result.block(f"preflight_result_time_invalid:{identifier}")
        verify_file_evidence(
            path_value=item.get("evidence_path"),
            hash_value=item.get("evidence_sha256"),
            base=root,
            result=result,
            label=f"preflight:{identifier}",
        )
    unknown = sorted(set(result_items).difference(checklist_items))
    for identifier in unknown:
        result.error(f"preflight_unknown_result:{identifier}")
    result.checks.update(
        {
            "checklist_items": len(checklist_items),
            "required_items": len(required_ids),
            "recorded_items": len(result_items),
            "results_path": str(results_path),
        }
    )
    return result


def preflight_contract() -> dict[str, Any]:
    """供文档和测试使用的结构化现场证据契约摘要。"""

    return {
        "exit_codes": {"PASS": 0, "ERROR": 1, "BLOCKED": 2},
        "real_source_types": sorted(ALLOWED_REAL_SOURCES),
        "required_technology_decisions": sorted(TECHNOLOGY_DECISION_IDS),
        "placeholder_pattern": PLACEHOLDER.pattern,
        "preflight_execution_mode": "validate-structured-results-only",
    }
