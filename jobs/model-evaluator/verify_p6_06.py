#!/usr/bin/env python3
"""P6-06 影子、灰度、正式切换和回滚的严格只读验证器。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = REPO_ROOT / "jobs" / "model-evaluator" / "controlled-output" / "p6-06"
REQUIRED_FILES = (
    "deployment-plan.json",
    "runtime-evidence.json",
    "shadow-report.json",
    "canary-report.json",
    "rollback-report.json",
    "deployment-events.json",
    "report.json",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_EVENT_STATES = (
    "REQUESTED",
    "APPROVED",
    "SHADOW_ACTIVE",
    "CANARY_ACTIVE",
    "PRODUCTION_ACTIVE",
    "ROLLBACK_EXECUTED",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"json_invalid:{path.name}:{type(exc).__name__}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"json_root_not_object:{path.name}")
        return {}
    return value


def required_uuid(value: Any, field: str, errors: list[str]) -> str:
    if not isinstance(value, str):
        errors.append(f"uuid_missing:{field}")
        return ""
    try:
        return str(uuid.UUID(value))
    except ValueError:
        errors.append(f"uuid_invalid:{field}")
        return ""


def required_hash(value: Any, field: str, errors: list[str]) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        errors.append(f"sha256_invalid:{field}")
        return ""
    return value


def verify_observation(
    report: dict[str, Any],
    name: str,
    model_version_id: str,
    package_sha256: str,
    errors: list[str],
    *,
    canary: bool,
) -> None:
    if report.get("schema_version") != f"p6-06-{name}-observation.v1":
        errors.append(f"{name}:schema_mismatch")
    if report.get("status") != "COMPLETE":
        errors.append(f"{name}:status_invalid:{report.get('status', 'MISSING')}")
    if report.get("model_version_id") != model_version_id:
        errors.append(f"{name}:model_version_mismatch")
    if report.get("package_sha256") != package_sha256:
        errors.append(f"{name}:package_hash_mismatch")
    if report.get("gate_state") != "APPROVED":
        errors.append(f"{name}:gate_not_approved")
    if report.get("observation_window_seconds", 0) <= 0:
        errors.append(f"{name}:observation_window_missing")
    minimum = report.get("minimum_sample_count")
    sample_count = report.get("sample_count")
    if not isinstance(minimum, int) or minimum <= 0:
        errors.append(f"{name}:minimum_sample_count_invalid")
    if not isinstance(sample_count, int) or sample_count < minimum:
        errors.append(f"{name}:sample_count_below_minimum")
    if not isinstance(report.get("metrics"), dict) or not report["metrics"]:
        errors.append(f"{name}:metrics_missing")
    if canary:
        ratio = report.get("traffic_ratio")
        if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not 0.0 < float(ratio) < 1.0:
            errors.append("canary:traffic_ratio_must_be_between_zero_and_one")
        station_ids = report.get("station_ids")
        if not isinstance(station_ids, list) or not station_ids or len(set(station_ids)) != len(station_ids):
            errors.append("canary:station_scope_missing_or_duplicate")
    else:
        if report.get("traffic_ratio") != 0:
            errors.append("shadow:traffic_ratio_must_be_zero")


def verify_package(package_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    for filename in REQUIRED_FILES:
        if not (package_dir / filename).is_file():
            errors.append(f"missing_file:{filename}")
    if errors:
        return {"status": "BLOCKED", "package": str(package_dir), "error_count": len(errors), "errors": errors[:120]}

    plan = read_json(package_dir / "deployment-plan.json", errors)
    runtime = read_json(package_dir / "runtime-evidence.json", errors)
    shadow = read_json(package_dir / "shadow-report.json", errors)
    canary = read_json(package_dir / "canary-report.json", errors)
    rollback = read_json(package_dir / "rollback-report.json", errors)
    events_payload = read_json(package_dir / "deployment-events.json", errors)
    report = read_json(package_dir / "report.json", errors)

    if plan.get("schema_version") != "p6-06-deployment-plan.v1":
        errors.append("plan:schema_mismatch")
    if plan.get("status") != "COMPLETE":
        errors.append(f"plan:status_invalid:{plan.get('status', 'MISSING')}")
    if plan.get("immutable") is not True:
        errors.append("plan:immutable_missing")
    if plan.get("p6_05_registry_status") != "COMPLETE":
        errors.append("plan:p6_05_registry_not_complete")
    model_version_id = required_uuid(plan.get("model_version_id"), "model_version_id", errors)
    rollback_model_version_id = required_uuid(plan.get("rollback_model_version_id"), "rollback_model_version_id", errors)
    package_sha256 = required_hash(plan.get("package_sha256"), "package_sha256", errors)
    rollback_package_sha256 = required_hash(plan.get("rollback_package_sha256"), "rollback_package_sha256", errors)
    if model_version_id and rollback_model_version_id and model_version_id == rollback_model_version_id:
        errors.append("plan:rollback_target_must_differ")
    if package_sha256 and rollback_package_sha256 and package_sha256 == rollback_package_sha256:
        errors.append("plan:rollback_package_must_differ")
    if plan.get("production_alias") != "production" or plan.get("stable_previous_alias") != "stable-previous":
        errors.append("plan:immutable_alias_binding_missing")
    target_ref = plan.get("target_ref")
    if not isinstance(target_ref, dict) or target_ref.get("model_version_id") != model_version_id or target_ref.get("package_sha256") != package_sha256:
        errors.append("plan:target_ref_mismatch")
    if isinstance(target_ref, dict) and any(key in target_ref for key in ("path", "directory", "mutable_target")):
        errors.append("plan:mutable_target_reference")

    if runtime.get("schema_version") != "p6-06-runtime-evidence.v1":
        errors.append("runtime:schema_mismatch")
    if runtime.get("status") != "COMPLETE":
        errors.append(f"runtime:status_invalid:{runtime.get('status', 'MISSING')}")
    if runtime.get("dual_slot") is not True:
        errors.append("runtime:dual_slot_missing")
    slots = runtime.get("slots")
    if not isinstance(slots, list) or len(slots) < 2:
        errors.append("runtime:two_slots_required")
        slots = []
    identities: set[tuple[str, str]] = set()
    target_ready = False
    rollback_ready = False
    for slot in slots:
        if not isinstance(slot, dict):
            errors.append("runtime:slot_not_object")
            continue
        slot_id = slot.get("slot_id")
        identity = (slot.get("model_version_id", ""), slot.get("package_sha256", ""))
        if not isinstance(slot_id, str) or not slot_id.strip():
            errors.append("runtime:slot_id_missing")
        if identity in identities:
            errors.append("runtime:duplicate_slot_identity")
        identities.add(identity)
        if slot.get("state") != "READY":
            errors.append(f"runtime:slot_not_ready:{slot_id}")
        if slot.get("signature_status") != "VERIFIED":
            errors.append(f"runtime:slot_signature_not_verified:{slot_id}")
        for field in ("warmed", "health_ready", "isolated"):
            if slot.get(field) is not True:
                errors.append(f"runtime:{field}_missing:{slot_id}")
        if slot.get("model_version_id") == model_version_id and slot.get("package_sha256") == package_sha256:
            target_ready = True
        if slot.get("model_version_id") == rollback_model_version_id and slot.get("package_sha256") == rollback_package_sha256:
            rollback_ready = True
    if not target_ready:
        errors.append("runtime:target_slot_not_ready")
    if not rollback_ready:
        errors.append("runtime:rollback_slot_not_ready")

    if model_version_id and package_sha256:
        verify_observation(shadow, "shadow", model_version_id, package_sha256, errors, canary=False)
        verify_observation(canary, "canary", model_version_id, package_sha256, errors, canary=True)

    if plan.get("production_status") != "ACTIVE":
        errors.append("plan:production_not_active")
    if plan.get("activated_after_canary") is not True:
        errors.append("plan:production_activation_order_missing")
    if plan.get("production_traffic_ratio") != 1:
        errors.append("plan:production_traffic_ratio_must_be_one")

    failure_cases = runtime.get("load_failure_cases")
    if not isinstance(failure_cases, list) or not failure_cases:
        errors.append("runtime:load_failure_safety_evidence_missing")
    else:
        for failure in failure_cases:
            if not isinstance(failure, dict):
                errors.append("runtime:load_failure_case_not_object")
                continue
            if failure.get("traffic_enabled") is not False:
                errors.append("runtime:load_failure_must_not_enable_traffic")
            if failure.get("state") not in {"HOLD", "FAILED"}:
                errors.append("runtime:load_failure_state_must_be_hold_or_failed")
            if failure.get("result") == "PASS":
                errors.append("runtime:load_failure_cannot_pass")

    if rollback.get("schema_version") != "p6-06-rollback-evidence.v1":
        errors.append("rollback:schema_mismatch")
    if rollback.get("status") != "COMPLETE":
        errors.append(f"rollback:status_invalid:{rollback.get('status', 'MISSING')}")
    if rollback.get("executed") is not True:
        errors.append("rollback:not_executed")
    if rollback.get("source_model_version_id") != model_version_id or rollback.get("source_package_sha256") != package_sha256:
        errors.append("rollback:source_identity_mismatch")
    if rollback.get("target_model_version_id") != rollback_model_version_id or rollback.get("target_package_sha256") != rollback_package_sha256:
        errors.append("rollback:target_identity_mismatch")
    for field in ("history_unchanged", "new_tasks_target_rollback", "existing_tasks_unchanged", "new_slot_drained", "evidence_preserved"):
        if rollback.get(field) is not True:
            errors.append(f"rollback:{field}_missing")
    if rollback.get("execution_mode") not in {"LIVE", "PRODUCTION_EQUIVALENT"}:
        errors.append("rollback:simulation_not_accepted")
    if not isinstance(rollback.get("reason"), str) or not rollback["reason"].strip():
        errors.append("rollback:reason_missing")
    if not isinstance(rollback.get("operator"), str) or not rollback["operator"].strip():
        errors.append("rollback:operator_missing")

    events = events_payload.get("events")
    if not isinstance(events, list):
        errors.append("events_missing")
        events = []
    observed_states: list[str] = []
    event_ids: set[str] = set()
    for event in events:
        if not isinstance(event, dict):
            errors.append("event_not_object")
            continue
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id or event_id in event_ids:
            errors.append("event_id_missing_or_duplicate")
        event_ids.add(str(event_id))
        state = event.get("state")
        observed_states.append(state)
        expected_hash = event.get("event_sha256")
        unsigned = {key: value for key, value in event.items() if key != "event_sha256"}
        if not isinstance(expected_hash, str) or expected_hash != hashlib.sha256(canonical_json(unsigned)).hexdigest():
            errors.append("event_hash_invalid")
        if not isinstance(event.get("actor_id"), str) or not event["actor_id"].strip():
            errors.append("event_actor_missing")
    if observed_states != list(REQUIRED_EVENT_STATES):
        errors.append("events:state_sequence_mismatch")

    if report.get("schema_version") != "p6-06-deployment-report.v1":
        errors.append("report:schema_mismatch")
    if report.get("status") != "COMPLETE":
        errors.append(f"report:status_invalid:{report.get('status', 'MISSING')}")
    if report.get("immutable") is not True:
        errors.append("report:immutable_missing")
    if report.get("production_release_allowed") is not True:
        errors.append("report:production_release_not_allowed")
    if report.get("model_version_id") != model_version_id or report.get("package_sha256") != package_sha256:
        errors.append("report:target_identity_mismatch")

    return {
        "status": "COMPLETE" if not errors else "BLOCKED",
        "package": str(package_dir),
        "slot_count": len(slots),
        "event_count": len(events),
        "error_count": len(errors),
        "errors": errors[:120],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="严格验证 P6-06 模型部署和回滚证据")
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    args = parser.parse_args(argv)
    try:
        result = verify_package(args.package_dir.resolve())
    except Exception as exc:
        result = {"status": "BLOCKED", "error_count": 1, "errors": [f"verifier_exception:{type(exc).__name__}:{exc}"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
