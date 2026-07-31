#!/usr/bin/env python3
"""P7 单项与阶段严格门禁。"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.p7.common import ValidationResult, read_json_object, repository_root
from tools.p7.preflight import (
    validate_config,
    validate_env,
    validate_model_package,
    validate_preflight_results,
    validate_smoke_evidence,
)
from tools.p7.hardware import validate_hardware_report
from tools.p7.migration import validate_p7_03_evidence
from tools.p7.nonfunctional import validate_nonfunctional_report
from tools.p7.quality import validate_quality_trial_report
from tools.p7.operations import validate_p7_06_evidence
from tools.p7.release import validate_g7_record, validate_p7_07_evidence


PYTHON_SCRIPT = re.compile(r"(?:^|\s)python(?:3)?\s+([^\s]+\.py)(?:\s|$)")


def _verify_g6_precondition(root: Path) -> ValidationResult:
    result = ValidationResult("p7-g6-precondition")
    path = root / "Docs/reports/P6-gate-acceptance.json"
    report = read_json_object(path, result, "p6_gate_acceptance")
    if not report:
        return result
    if report.get("status") != "PASS":
        result.block(f"p6_gate_not_pass:{report.get('status')}")
    task_results = report.get("task_results")
    if not isinstance(task_results, list):
        result.block("p6_gate_task_results_missing")
    else:
        by_task = {
            item.get("task_id"): item
            for item in task_results
            if isinstance(item, dict) and isinstance(item.get("task_id"), str)
        }
        for number in range(1, 9):
            task_id = f"P6-{number:02d}"
            if by_task.get(task_id, {}).get("status") != "PASS":
                result.block(f"p6_gate_task_not_pass:{task_id}")
    result.checks["path"] = str(path)
    return result


def _verify_checklist_scripts(root: Path) -> ValidationResult:
    result = ValidationResult("p7-preflight-script-references")
    checklist_path = root / "deploy/environments/production/checklists/pre-flight.json"
    checklist = read_json_object(checklist_path, result, "preflight_checklist")
    items = checklist.get("items") if checklist else None
    if not isinstance(items, list):
        if checklist:
            result.error("preflight_checklist_items_invalid")
        return result
    referenced: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            result.error("preflight_checklist_item_not_object")
            continue
        command = item.get("verification_command")
        if not isinstance(command, str) or not command.strip():
            result.error(f"preflight_command_missing:{item.get('id')}")
            continue
        match = PYTHON_SCRIPT.search(command)
        if match is None:
            continue
        relative = match.group(1)
        referenced.add(relative)
        if not (root / relative).is_file():
            result.error(f"preflight_script_missing:{item.get('id')}:{relative}")
    aggregate = root / "deploy/environments/production/checklists/validate_preflight.py"
    if not aggregate.is_file():
        result.error("preflight_aggregate_script_missing")
    result.checks["referenced_python_scripts"] = sorted(referenced)
    return result


def verify_p7_01(root: Path) -> ValidationResult:
    result = ValidationResult("verify-p7-01")
    result.merge(_verify_g6_precondition(root), "g6")
    result.merge(_verify_checklist_scripts(root), "script_references")
    result.merge(validate_config(repo_root=root), "config")
    result.merge(validate_env(repo_root=root), "environment")
    result.merge(validate_model_package(repo_root=root), "model_package")
    result.merge(validate_smoke_evidence(repo_root=root), "model_smoke")
    result.merge(validate_preflight_results(repo_root=root), "preflight_results")
    result.checks["contract_version"] = "v1"
    result.checks["openapi_generated_package_version"] = "1.0.0"
    return result


def verify_p7_02(root: Path) -> ValidationResult:
    result = ValidationResult("verify-p7-02")
    result.merge(verify_p7_01(root), "p7_01")
    result.merge(validate_hardware_report(repo_root=root), "hardware")
    return result


def verify_p7_03(root: Path) -> ValidationResult:
    result = ValidationResult("verify-p7-03")
    result.merge(verify_p7_01(root), "p7_01")
    result.merge(validate_p7_03_evidence(repo_root=root), "migration_recovery")
    return result


def verify_p7_04(root: Path) -> ValidationResult:
    result = ValidationResult("verify-p7-04")
    result.merge(verify_p7_02(root), "p7_02")
    result.merge(verify_p7_03(root), "p7_03")
    result.merge(validate_nonfunctional_report(repo_root=root), "nonfunctional")
    return result


def verify_p7_05(root: Path) -> ValidationResult:
    result = ValidationResult("verify-p7-05")
    result.merge(verify_p7_04(root), "p7_04")
    result.merge(validate_quality_trial_report(repo_root=root), "quality_trial")
    return result


def verify_p7_06(root: Path) -> ValidationResult:
    result = ValidationResult("verify-p7-06")
    result.merge(verify_p7_04(root), "p7_04")
    result.merge(validate_p7_06_evidence(repo_root=root), "operations")
    return result


def verify_p7_07(root: Path) -> ValidationResult:
    """直接汇总六项任务证据，避免嵌套前置造成重复阻断。"""

    result = ValidationResult("verify-p7-07")
    result.merge(verify_p7_01(root), "p7_01")
    result.merge(validate_hardware_report(repo_root=root), "p7_02")
    result.merge(validate_p7_03_evidence(repo_root=root), "p7_03")
    result.merge(validate_nonfunctional_report(repo_root=root), "p7_04")
    result.merge(validate_quality_trial_report(repo_root=root), "p7_05")
    result.merge(validate_p7_06_evidence(repo_root=root), "p7_06")
    result.merge(validate_p7_07_evidence(repo_root=root), "release")
    return result


def verify_g7(root: Path) -> ValidationResult:
    result = ValidationResult("verify-g7")
    result.merge(verify_p7_07(root), "p7_07")
    result.merge(validate_g7_record(repo_root=root), "gate_record")
    result.checks["contract_version"] = "v1"
    result.checks["openapi_generated_package_version"] = "1.0.0"
    return result


def verify(task: str, root: Path | None = None) -> ValidationResult:
    repo_root = (root or repository_root()).resolve()
    if task == "P7-01":
        return verify_p7_01(repo_root)
    if task == "P7-02":
        return verify_p7_02(repo_root)
    if task == "P7-03":
        return verify_p7_03(repo_root)
    if task == "P7-04":
        return verify_p7_04(repo_root)
    if task == "P7-05":
        return verify_p7_05(repo_root)
    if task == "P7-06":
        return verify_p7_06(repo_root)
    if task == "P7-07":
        return verify_p7_07(repo_root)
    if task == "G7":
        return verify_g7(repo_root)
    result = ValidationResult(f"verify-{task.lower()}")
    result.error(f"unsupported_p7_task:{task}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "task",
        choices=(
            "P7-01",
            "P7-02",
            "P7-03",
            "P7-04",
            "P7-05",
            "P7-06",
            "P7-07",
            "G7",
        ),
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    return verify(args.task, args.repo_root).emit()


if __name__ == "__main__":
    raise SystemExit(main())
