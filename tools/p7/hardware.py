"""P7-02 真实相机、PLC/传感器现场报告严格验证。"""

from __future__ import annotations

from collections import Counter
import os
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


REQUIRED_TESTS = {
    "camera_connectivity",
    "trigger_signal_detection",
    "single_frame_capture",
    "continuous_capture",
    "trigger_to_capture_latency",
    "dark_and_saturation",
    "multi_camera_sync",
    "overnight_stability",
    "external_network_outage",
    "external_agent_restart",
    "external_driver_failure",
    "external_disk_watermark",
    "external_clock_skew",
    "external_browser_failure",
}


def _index_tests(value: Any, result: ValidationResult) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        result.error("hardware_report_tests_not_array")
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            result.error(f"hardware_report_test_not_object:{index}")
            continue
        name = item.get("test_name")
        if not isinstance(name, str) or not name.strip():
            result.error(f"hardware_report_test_name_missing:{index}")
            continue
        if name in indexed:
            result.error(f"hardware_report_test_duplicate:{name}")
            continue
        indexed[name] = item
    return indexed


def validate_hardware_report(
    *,
    repo_root: Path | None = None,
    report_path: Path | None = None,
    config_path: Path | None = None,
) -> ValidationResult:
    root = (repo_root or repository_root()).resolve()
    if report_path is None:
        configured = os.environ.get("P7_HARDWARE_REPORT")
        report_path = Path(configured) if configured else root / "deploy/environments/production/evidence/hardware-acceptance-report.json"
    if config_path is None:
        configured = os.environ.get("P7_HARDWARE_CONFIG")
        config_path = Path(configured) if configured else root / "deploy/environments/production/evidence/site-hardware-config.json"
    result = ValidationResult("p7-hardware-acceptance")
    report = read_json_object(report_path, result, "hardware_acceptance_report")
    config = read_json_object(config_path, result, "hardware_acceptance_config")
    if not report or not config:
        return result
    if ".template." in report_path.name.lower() or ".template." in config_path.name.lower():
        result.block("hardware_template_not_acceptable")
    if report.get("schema_version") != "tool-defect-hardware-acceptance-report/v1":
        result.block("hardware_report_schema_invalid")
    if config.get("schema_version") != "tool-defect-hardware-acceptance/v1":
        result.block("hardware_config_schema_invalid")
    if report.get("source_type") != "REAL_HARDWARE" or config.get("source_type") != "REAL_HARDWARE":
        result.block("hardware_source_not_real")
    if report.get("overall_status") != "PASS":
        result.block(f"hardware_report_not_pass:{report.get('overall_status')}")
    if report.get("production_claim_allowed") is not True:
        result.block("hardware_production_claim_not_allowed")
    for field in ("report_id", "site_id", "hostname", "approved_by"):
        if is_placeholder(report.get(field)):
            result.block(f"hardware_report_{field}_missing")
    for field in ("generated_at", "started_at", "approved_at"):
        if not valid_iso8601(report.get(field)):
            result.block(f"hardware_report_{field}_invalid")
    for field in ("config_sha256", "script_sha256"):
        value = report.get(field)
        if not isinstance(value, str) or SHA256.fullmatch(value) is None:
            result.block(f"hardware_report_{field}_invalid")
    if report.get("config_sha256") != sha256_file(config_path):
        result.block("hardware_config_sha256_mismatch")
    runner_path = root / "apps/edge-agent/scripts/hardware_acceptance.py"
    if not runner_path.is_file():
        result.error("hardware_runner_missing")
    elif report.get("script_sha256") != sha256_file(runner_path):
        result.block("hardware_runner_sha256_mismatch")
    verify_file_evidence(
        path_value=report.get("approval_evidence_path"),
        hash_value=report.get("approval_evidence_sha256"),
        base=config_path.parent,
        result=result,
        label="hardware_approval",
    )

    inventory = report.get("device_inventory")
    if inventory != config.get("device_inventory"):
        result.block("hardware_device_inventory_binding_mismatch")
    if not isinstance(inventory, dict):
        result.block("hardware_device_inventory_missing")
    else:
        for device_name in ("camera", "trigger"):
            device = inventory.get(device_name)
            if not isinstance(device, dict):
                result.block(f"hardware_inventory_{device_name}_missing")
                continue
            for field in (
                "vendor",
                "model",
                "serial_number",
                "firmware_version",
                "driver_version",
                "sdk_version",
            ):
                if is_placeholder(device.get(field)):
                    result.block(f"hardware_inventory_{device_name}_{field}_missing")

    tests = _index_tests(report.get("tests"), result)
    for name in sorted(REQUIRED_TESTS.difference(tests)):
        result.block(f"hardware_required_test_missing:{name}")
    for name, test in tests.items():
        if test.get("status") != "PASS":
            result.block(f"hardware_test_not_pass:{name}:{test.get('status')}")
    status_counts = Counter(str(item.get("status")) for item in tests.values())
    summary = report.get("summary")
    if not isinstance(summary, dict):
        result.error("hardware_report_summary_missing")
    else:
        expected_total = len(tests)
        if summary.get("total") != expected_total:
            result.error("hardware_report_summary_total_mismatch")
        if summary.get("pass") != status_counts["PASS"]:
            result.error("hardware_report_summary_pass_mismatch")
        for field in ("fail", "pending_hardware", "skipped", "not_implemented", "warn"):
            if summary.get(field) != 0:
                result.block(f"hardware_report_summary_nonzero:{field}")

    trigger = tests.get("trigger_signal_detection", {}).get("evidence")
    if not isinstance(trigger, dict):
        result.block("hardware_trigger_evidence_missing")
    else:
        if trigger.get("duplicate_sequences") != 0:
            result.block("hardware_trigger_duplicates_present")
        if trigger.get("sequence_gaps") != []:
            result.block("hardware_trigger_sequence_gaps_present")
        events = trigger.get("events_detected")
        minimum = trigger.get("minimum_events")
        if not isinstance(events, int) or not isinstance(minimum, int) or events < minimum:
            result.block("hardware_trigger_sample_count_insufficient")

    continuous = tests.get("continuous_capture", {}).get("evidence")
    if not isinstance(continuous, dict):
        result.block("hardware_continuous_evidence_missing")
    elif continuous.get("frames_failed") != 0:
        result.block("hardware_continuous_frames_failed")
    stability = tests.get("overnight_stability", {}).get("evidence")
    if not isinstance(stability, dict):
        result.block("hardware_stability_evidence_missing")
    else:
        duration = stability.get("duration_s")
        minimum = stability.get("minimum_duration_s")
        if not isinstance(duration, (int, float)) or not isinstance(minimum, (int, float)) or duration < minimum:
            result.block("hardware_stability_duration_insufficient")
        if stability.get("failures") != 0:
            result.block("hardware_stability_failures_present")
    quality = tests.get("dark_and_saturation", {}).get("evidence")
    if not isinstance(quality, dict) or quality.get("pixel_analysis_completed") is not True:
        result.block("hardware_pixel_quality_analysis_missing")

    result.checks.update(
        {
            "report_path": str(report_path),
            "config_path": str(config_path),
            "test_count": len(tests),
            "required_test_count": len(REQUIRED_TESTS),
        }
    )
    return result
