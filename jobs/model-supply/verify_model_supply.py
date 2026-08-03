#!/usr/bin/env python3
"""R8 模型包供应链只读验证入口。

没有压缩包、声明哈希、资源限制或信任根时返回失败/HOLD；该脚本没有空目标成功路径，
也不会启动模型运行时或访问业务数据库。
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tool_defect.models.archive import (  # noqa: E402
    ArchiveLimits,
    ModelArchiveViolation,
    extract_verified_model_archive,
    verify_model_archive,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="验证 R8 外部模型压缩包")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--declared-size", type=int, required=True)
    parser.add_argument("--declared-sha256", required=True)
    parser.add_argument("--trusted-keys", type=Path, required=True)
    parser.add_argument(
        "--policy",
        type=Path,
        default=REPO_ROOT / "deploy/security/supply-chain-policy.json",
    )
    parser.add_argument("--maximum-archive-bytes", type=int, default=8 * 1024 * 1024 * 1024)
    parser.add_argument("--maximum-member-bytes", type=int, default=8 * 1024 * 1024 * 1024)
    parser.add_argument("--maximum-total-uncompressed-bytes", type=int, default=8 * 1024 * 1024 * 1024)
    parser.add_argument("--maximum-entries", type=int, default=128)
    parser.add_argument("--maximum-compression-ratio", type=int, default=1000)
    args = parser.parse_args(argv)

    try:
        policy = _load_policy(args.policy)
        trusted_keys = _load_trusted_keys(args.trusted_keys)
        limits = ArchiveLimits(
            maximum_archive_bytes=args.maximum_archive_bytes,
            maximum_member_bytes=args.maximum_member_bytes,
            maximum_total_uncompressed_bytes=args.maximum_total_uncompressed_bytes,
            maximum_entries=args.maximum_entries,
            maximum_compression_ratio=args.maximum_compression_ratio,
        )
        _require_within_policy(limits, policy["resource_limits"])
        evidence = verify_model_archive(
            args.archive,
            declared_size_bytes=args.declared_size,
            declared_sha256=args.declared_sha256,
            trusted_public_keys=trusted_keys,
            limits=limits,
            required_files=frozenset(policy["required_files"]),
            optional_files=frozenset(policy.get("optional_files", [])),
            forbidden_suffixes=frozenset(policy["forbidden_suffixes"]),
        )
        _validate_manifest(evidence.manifest, policy)
        with tempfile.TemporaryDirectory(prefix="td-model-verify-") as directory:
            extracted = extract_verified_model_archive(args.archive, Path(directory), evidence, limits=limits)
            _validate_sbom(extracted / policy["sbom"]["file"], policy["sbom"])
    except ModelArchiveViolation as error:
        _print(
            {
                "status": "BLOCKED",
                "error_code": error.code,
                "message": str(error),
            }
        )
        return 1
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError) as error:
        _print(
            {
                "status": "HOLD",
                "error_code": "VALIDATION_CONFIGURATION_INVALID",
                "message": "模型供应链验证配置或状态未知",
                "exception_type": type(error).__name__,
            }
        )
        return 2

    _print(
        {
            "status": "COMPLETE",
            "archive_sha256": evidence.archive_sha256,
            "archive_size_bytes": evidence.archive_size_bytes,
            "member_count": len(evidence.member_sha256),
            "signer_key_id": evidence.signer_key_id,
            "model_name": evidence.manifest["model_name"],
            "model_version": evidence.manifest["model_version"],
        }
    )
    return 0


def _load_policy(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    package = value["model_packages"]
    required = package["required_files"]
    forbidden = package["forbidden_suffixes"]
    resource_limits = package["resource_limits"]
    allowed_frameworks = package["allowed_frameworks"]
    allowed_plugins = package["allowed_plugins"]
    sbom = package["sbom"]
    if (
        not isinstance(required, list)
        or not required
        or any(not isinstance(item, str) or not item for item in required)
        or len(set(required)) != len(required)
        or not isinstance(forbidden, list)
        or any(not isinstance(item, str) or not item.startswith(".") for item in forbidden)
        or not isinstance(resource_limits, dict)
        or not isinstance(allowed_frameworks, dict)
        or not allowed_frameworks
        or not isinstance(allowed_plugins, dict)
        or not isinstance(sbom, dict)
        or not isinstance(sbom.get("file"), str)
        or not isinstance(sbom.get("spec_versions"), list)
        or not sbom.get("spec_versions")
    ):
        raise ValueError("模型包安全策略文件清单无效")
    return {
        "required_files": required,
        "forbidden_suffixes": forbidden,
        "resource_limits": resource_limits,
        "allowed_frameworks": allowed_frameworks,
        "allowed_plugins": allowed_plugins,
        "sbom": sbom,
    }


def _require_within_policy(limits: ArchiveLimits, policy: dict[str, Any]) -> None:
    fields = (
        "maximum_archive_bytes",
        "maximum_member_bytes",
        "maximum_total_uncompressed_bytes",
        "maximum_entries",
        "maximum_compression_ratio",
    )
    if any(not isinstance(policy.get(field), int) or policy[field] <= 0 for field in fields):
        raise ValueError("模型包资源限制策略无效")
    requested = tuple(getattr(limits, field) for field in fields)
    approved = tuple(policy[field] for field in fields)
    if any(value > maximum for value, maximum in zip(requested, approved)):
        raise ValueError("命令行模型包资源限制超过已批准策略")


def _validate_manifest(manifest: dict[str, Any] | Any, policy: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise ModelArchiveViolation("MANIFEST_INVALID", "模型包清单无效")
    framework = manifest.get("framework")
    framework_version = manifest.get("framework_version")
    versions = policy["allowed_frameworks"].get(framework)
    if (
        not isinstance(framework, str)
        or not isinstance(framework_version, str)
        or not isinstance(versions, list)
        or framework_version not in versions
    ):
        raise ModelArchiveViolation("FRAMEWORK_NOT_ALLOWED", "模型框架或版本不在白名单")
    preprocessor = manifest.get("preprocessor")
    if not isinstance(preprocessor, dict):
        raise ModelArchiveViolation("PLUGIN_DECLARATION_MISSING", "模型清单缺少插件声明")
    plugin_id = preprocessor.get("plugin_id")
    plugin_version = preprocessor.get("plugin_version")
    allowed_versions = policy["allowed_plugins"].get(plugin_id)
    if (
        not isinstance(plugin_id, str)
        or not isinstance(plugin_version, str)
        or not isinstance(allowed_versions, list)
        or plugin_version not in allowed_versions
    ):
        raise ModelArchiveViolation("PLUGIN_NOT_ALLOWED", "模型插件或版本不在白名单")


def _validate_sbom(path: Path, policy: dict[str, Any]) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelArchiveViolation("SBOM_INVALID", "模型软件物料清单不可读") from error
    if not isinstance(value, dict) or value.get("bomFormat") != policy["format"]:
        raise ModelArchiveViolation("SBOM_INVALID", "模型软件物料清单格式不受支持")
    if value.get("specVersion") not in policy["spec_versions"]:
        raise ModelArchiveViolation("SBOM_INVALID", "模型软件物料清单版本不受支持")
    components = value.get("components")
    if policy.get("require_components") and (not isinstance(components, list) or not components):
        raise ModelArchiveViolation("SBOM_INVALID", "模型软件物料清单缺少组件")
    identities: set[str] = set()
    for component in components or []:
        if not isinstance(component, dict):
            raise ModelArchiveViolation("SBOM_INVALID", "模型软件物料清单组件无效")
        name = component.get("name")
        version = component.get("version")
        if not isinstance(name, str) or not name.strip() or not isinstance(version, str) or not version.strip():
            raise ModelArchiveViolation("SBOM_INVALID", "模型软件物料清单组件缺少名称或版本")
        identity = str(component.get("purl") or f"{name}@{version}")
        if identity in identities:
            raise ModelArchiveViolation("SBOM_INVALID", "模型软件物料清单包含重复组件")
        identities.add(identity)


def _load_trusted_keys(path: Path) -> dict[str, bytes]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not value:
        raise ValueError("模型签名信任根为空")
    result: dict[str, bytes] = {}
    for key_id, encoded in value.items():
        if not isinstance(key_id, str) or not key_id.strip() or not isinstance(encoded, str):
            raise ValueError("模型签名信任根格式无效")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except ValueError:
            decoded = bytes.fromhex(encoded)
        if len(decoded) != 32:
            raise ValueError("模型签名信任根长度无效")
        if key_id in result:
            raise ValueError("模型签名信任根包含重复标识")
        result[key_id] = decoded
    return result


def _print(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    raise SystemExit(main())
