#!/usr/bin/env python3
"""P6-05 模型登记、供应链证据和独立审批的严格只读验证器。

验证器会重新校验模型包的校验和与 Ed25519 签名，不信任登记表中单独声明的
``signature_verified`` 或 ``status``。SBOM、训练/数据集/评估引用、双角色审批
和不可变别名任一缺失都返回 BLOCKED。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = REPO_ROOT / "jobs" / "model-evaluator" / "controlled-output" / "p6-05"
REQUIRED_FILES = (
    "registry.json",
    "approvals.json",
    "aliases.json",
    "provenance.json",
    "report.json",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MODEL_STATES = {"APPROVED", "RETIRED"}
APPROVAL_ROLES = {"QUALITY_APPROVER", "MODEL_RELEASE_APPROVER"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def stable_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重复 JSON 字段: {key}")
        result[key] = value
    return result


def read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"非有限 JSON 常量: {value}")
            ),
        )
    except Exception as exc:
        errors.append(f"json_invalid:{path.name}:{type(exc).__name__}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"json_root_not_object:{path.name}")
        return {}
    return value


def resolve_evidence_path(value: Any, package_dir: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = package_dir / candidate
    try:
        return candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def load_public_keys(path: Path | None, errors: list[str]) -> dict[str, bytes]:
    if path is None:
        errors.append("trusted_keys_missing")
        return {}
    payload = read_json(path, errors)
    keys: dict[str, bytes] = {}
    for key_id, encoded in payload.items():
        if not isinstance(key_id, str) or not key_id.strip():
            errors.append("trusted_key_id_invalid")
            continue
        if not isinstance(encoded, str):
            errors.append(f"trusted_key_encoding_invalid:{key_id}")
            continue
        try:
            value = base64.b64decode(encoded, validate=True)
        except Exception:
            try:
                value = bytes.fromhex(encoded)
            except ValueError:
                errors.append(f"trusted_key_encoding_invalid:{key_id}")
                continue
        if len(value) != 32:
            errors.append(f"trusted_key_length_invalid:{key_id}")
            continue
        keys[key_id] = value
    if not keys:
        errors.append("trusted_keys_empty")
    return keys


def verify_sbom(path: Path, expected_sha256: Any, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"sbom_missing:{path}")
        return
    if not isinstance(expected_sha256, str) or SHA256.fullmatch(expected_sha256) is None:
        errors.append("sbom_hash_invalid")
    elif sha256_file(path) != expected_sha256:
        errors.append("sbom_hash_mismatch")
    payload = read_json(path, errors)
    if payload.get("bomFormat") != "CycloneDX":
        errors.append("sbom_format_invalid")
    if payload.get("specVersion") not in {"1.4", "1.5", "1.6"}:
        errors.append("sbom_spec_version_invalid")
    components = payload.get("components")
    if not isinstance(components, list) or not components:
        errors.append("sbom_components_missing")
        return
    coordinates: list[str] = []
    for component in components:
        if not isinstance(component, dict):
            errors.append("sbom_component_not_object")
            continue
        if not isinstance(component.get("name"), str) or not component["name"].strip():
            errors.append("sbom_component_name_missing")
        if not isinstance(component.get("version"), str) or not component["version"].strip():
            errors.append("sbom_component_version_missing")
        coordinate = component.get("purl") or f"{component.get('name')}@{component.get('version')}"
        if coordinate in coordinates:
            errors.append("sbom_duplicate_component")
        coordinates.append(coordinate)


def verify_evidence_hash(
    record: Mapping[str, Any],
    path_field: str,
    hash_field: str,
    package_dir: Path,
    errors: list[str],
) -> None:
    path = resolve_evidence_path(record.get(path_field), package_dir)
    expected = record.get(hash_field)
    if path is None:
        errors.append(f"evidence_path_missing:{path_field}")
        return
    if not isinstance(expected, str) or SHA256.fullmatch(expected) is None:
        errors.append(f"evidence_hash_invalid:{hash_field}")
        return
    if sha256_file(path) != expected:
        errors.append(f"evidence_hash_mismatch:{hash_field}")
    payload_errors: list[str] = []
    payload = read_json(path, payload_errors)
    if payload_errors:
        errors.extend(f"{path.name}:{item}" for item in payload_errors)
    if payload.get("status") in {"BLOCKED", "HOLD", "FAILED"}:
        errors.append(f"evidence_not_usable:{path.name}")


def verify_model_package(
    record: Mapping[str, Any],
    package_dir: Path,
    trusted_keys: Mapping[str, bytes],
    errors: list[str],
) -> None:
    required = {
        "model_version_id",
        "model_name",
        "model_version",
        "state",
        "registered_by",
        "training_run_id",
        "dataset_version_id",
        "package_dir",
        "package_sha256",
        "sbom_path",
        "sbom_sha256",
        "signature_key_id",
        "evaluation_report_path",
        "evaluation_report_sha256",
        "threshold_gate_path",
        "threshold_gate_sha256",
    }
    missing = sorted(required.difference(record))
    errors.extend(f"model_field_missing:{field}" for field in missing)
    if missing:
        return
    for field in ("model_version_id", "model_name", "model_version", "registered_by", "training_run_id", "dataset_version_id"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            errors.append(f"model_field_invalid:{field}")
    if record.get("state") not in MODEL_STATES:
        errors.append(f"model_state_invalid:{record.get('state')}")
    package_hash = record.get("package_sha256")
    if not isinstance(package_hash, str) or SHA256.fullmatch(package_hash) is None:
        errors.append("model_package_hash_invalid")
    if not isinstance(record.get("signature_key_id"), str) or not record["signature_key_id"].strip():
        errors.append("model_signature_key_id_missing")

    package_value = record.get("package_dir")
    package_path = resolve_evidence_path(package_value, package_dir)
    if package_path is None:
        errors.append("model_package_path_missing")
        return

    try:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from tool_defect.models.package import (
            ApprovedArtifact,
            Ed25519SignatureVerifier,
            ModelPackageVerifier,
        )

        verifier = ModelPackageVerifier(
            Ed25519SignatureVerifier(trusted_keys),
            allowed_python_versions=(f"{sys.version_info.major}.{sys.version_info.minor}",),
        )
        verified = verifier.verify(
            package_path,
            ApprovedArtifact(
                model_name=str(record["model_name"]),
                model_version=str(record["model_version"]),
                package_sha256=str(record["package_sha256"]),
                signer_key_id=str(record["signature_key_id"]),
                approval_state="DEPLOYABLE",
            ),
        )
    except Exception as exc:
        errors.append(f"model_package_verification_failed:{type(exc).__name__}")
        return

    if verified.package_sha256 != package_hash:
        errors.append("model_package_hash_mismatch")
    if verified.signer_key_id != record.get("signature_key_id"):
        errors.append("model_signature_key_mismatch")
    if verified.manifest.dataset_version != record.get("dataset_version_id"):
        errors.append("model_dataset_binding_mismatch")
    if verified.manifest.source_run_id != record.get("training_run_id"):
        errors.append("model_training_binding_mismatch")

    sbom_path = resolve_evidence_path(record.get("sbom_path"), package_dir)
    if sbom_path is None:
        errors.append("model_sbom_path_missing")
    else:
        verify_sbom(sbom_path, record.get("sbom_sha256"), errors)
    verify_evidence_hash(
        record,
        "evaluation_report_path",
        "evaluation_report_sha256",
        package_dir,
        errors,
    )
    verify_evidence_hash(
        record,
        "threshold_gate_path",
        "threshold_gate_sha256",
        package_dir,
        errors,
    )


def verify_package(package_dir: Path, trusted_key_path: Path | None) -> dict[str, Any]:
    errors: list[str] = []
    for filename in REQUIRED_FILES:
        if not (package_dir / filename).is_file():
            errors.append(f"missing_file:{filename}")
    if errors:
        return {"status": "BLOCKED", "package": str(package_dir), "error_count": len(errors), "errors": errors[:120]}

    registry = read_json(package_dir / "registry.json", errors)
    approvals_payload = read_json(package_dir / "approvals.json", errors)
    aliases_payload = read_json(package_dir / "aliases.json", errors)
    provenance = read_json(package_dir / "provenance.json", errors)
    report = read_json(package_dir / "report.json", errors)
    trusted_keys = load_public_keys(trusted_key_path, errors)

    if registry.get("schema_version") != "p6-05-model-registry.v1":
        errors.append("registry_schema_mismatch")
    if registry.get("status") != "COMPLETE":
        errors.append(f"registry_status_invalid:{registry.get('status', 'MISSING')}")
    if provenance.get("immutable") is not True:
        errors.append("provenance_immutable_missing")
    if provenance.get("production_claim_allowed") is not False:
        errors.append("provenance_production_claim_must_be_false")
    if report.get("status") != "COMPLETE":
        errors.append(f"report_status_invalid:{report.get('status', 'MISSING')}")
    if report.get("immutable") is not True:
        errors.append("report_immutable_missing")
    if report.get("production_release_allowed") is not True:
        errors.append("report_production_release_not_allowed")

    models = registry.get("models")
    if not isinstance(models, list) or not models:
        errors.append("registry_models_missing")
        models = []
    model_by_id: dict[str, Mapping[str, Any]] = {}
    for record in models:
        if not isinstance(record, dict):
            errors.append("registry_model_not_object")
            continue
        model_id = record.get("model_version_id")
        if not isinstance(model_id, str) or not model_id.strip() or model_id in model_by_id:
            errors.append("registry_model_id_missing_or_duplicate")
            continue
        model_by_id[model_id] = record
        verify_model_package(record, package_dir, trusted_keys, errors)

    approval_items = approvals_payload.get("approvals")
    if not isinstance(approval_items, list):
        errors.append("approvals_missing")
        approval_items = []
    approvals_by_model: dict[str, list[Mapping[str, Any]]] = {}
    approval_ids: set[str] = set()
    for approval in approval_items:
        if not isinstance(approval, dict):
            errors.append("approval_not_object")
            continue
        approval_id = approval.get("approval_id")
        model_id = approval.get("model_version_id")
        role = approval.get("role")
        actor = approval.get("actor_id")
        if not isinstance(approval_id, str) or not approval_id or approval_id in approval_ids:
            errors.append("approval_id_missing_or_duplicate")
        else:
            approval_ids.add(approval_id)
        if model_id not in model_by_id:
            errors.append("approval_model_not_registered")
        if role not in APPROVAL_ROLES:
            errors.append(f"approval_role_invalid:{role}")
        if approval.get("decision") != "APPROVE":
            errors.append("approval_decision_not_approved")
        if not isinstance(actor, str) or not actor.strip():
            errors.append("approval_actor_missing")
        if approval.get("independent") is not True:
            errors.append("approval_independent_missing")
        if not isinstance(approval.get("approved_at"), str) or not approval["approved_at"].strip():
            errors.append("approval_time_missing")
        evidence_hash = approval.get("evidence_sha256")
        if not isinstance(evidence_hash, str) or SHA256.fullmatch(evidence_hash) is None:
            errors.append("approval_evidence_hash_invalid")
        evidence_path = resolve_evidence_path(approval.get("evidence_path"), package_dir)
        if evidence_path is None:
            errors.append("approval_evidence_path_missing")
        elif not evidence_path.is_file():
            errors.append("approval_evidence_file_missing")
        elif isinstance(evidence_hash, str) and SHA256.fullmatch(evidence_hash) is not None:
            if sha256_file(evidence_path) != evidence_hash:
                errors.append("approval_evidence_hash_mismatch")
        if isinstance(model_id, str):
            approvals_by_model.setdefault(model_id, []).append(approval)

    for model_id, record in model_by_id.items():
        if record.get("state") not in MODEL_STATES:
            continue
        records = approvals_by_model.get(model_id, [])
        roles = {item.get("role") for item in records}
        if roles != APPROVAL_ROLES:
            errors.append(f"approval_roles_incomplete:{model_id}")
        actors = {item.get("actor_id") for item in records if isinstance(item.get("actor_id"), str)}
        if len(actors) != 2 or record.get("registered_by") in actors:
            errors.append(f"approval_actor_separation_failed:{model_id}")
        referenced = record.get("approval_ids")
        if not isinstance(referenced, list) or not set(referenced).issubset(approval_ids):
            errors.append(f"approval_reference_invalid:{model_id}")

    aliases = aliases_payload.get("aliases")
    if not isinstance(aliases, list):
        errors.append("aliases_missing")
        aliases = []
    alias_by_name: dict[str, Mapping[str, Any]] = {}
    for alias in aliases:
        if not isinstance(alias, dict):
            errors.append("alias_not_object")
            continue
        name = alias.get("alias")
        if not isinstance(name, str) or not name.strip() or name in alias_by_name:
            errors.append("alias_name_missing_or_duplicate")
            continue
        alias_by_name[name] = alias
        if alias.get("immutable") is not True:
            errors.append(f"alias_not_immutable:{name}")
        target = alias.get("model_version_id")
        record = model_by_id.get(target)
        if record is None:
            errors.append(f"alias_target_missing:{name}")
            continue
        if alias.get("package_sha256") != record.get("package_sha256"):
            errors.append(f"alias_hash_mismatch:{name}")
        if "path" in alias or "directory" in alias or "mutable_target" in alias:
            errors.append(f"alias_mutable_reference:{name}")
        if name == "production" and record.get("state") != "APPROVED":
            errors.append("production_alias_requires_approved_model")
    if "production" not in alias_by_name:
        errors.append("production_alias_missing")
    if "stable-previous" not in alias_by_name:
        errors.append("stable_previous_alias_missing")
    else:
        previous = alias_by_name["stable-previous"]
        if previous.get("model_version_id") == alias_by_name.get("production", {}).get("model_version_id"):
            errors.append("stable_previous_must_differ_from_production")

    return {
        "status": "COMPLETE" if not errors else "BLOCKED",
        "package": str(package_dir),
        "model_count": len(models),
        "alias_count": len(aliases),
        "error_count": len(errors),
        "errors": errors[:120],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="严格验证 P6-05 模型登记和签名证据")
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--trusted-keys", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_package(args.package_dir.resolve(), args.trusted_keys.resolve() if args.trusted_keys else None)
    except Exception as exc:
        result = {"status": "BLOCKED", "error_count": 1, "errors": [f"verifier_exception:{type(exc).__name__}:{exc}"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
