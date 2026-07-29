"""命令行验证不可变模型包并输出机器可读报告。"""

import argparse
from base64 import b64decode
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tool_defect.models.package import (
    ApprovedArtifact,
    Ed25519SignatureVerifier,
    ModelPackageVerifier,
)
from tool_defect.plugin_api import PluginError


def verify_from_files(
    package_root: Path,
    approval_path: Path,
    trusted_keys_path: Path,
) -> dict:
    approval_payload = _object(approval_path)
    key_payload = _object(trusted_keys_path)
    approval_fields = {
        "model_name",
        "model_version",
        "package_sha256",
        "signer_key_id",
        "approval_state",
    }
    if set(approval_payload) != approval_fields:
        raise ValueError("批准记录字段不完整或包含未知字段")
    if not key_payload:
        raise ValueError("受信签名密钥集合不能为空")
    if any(
        not isinstance(key_id, str)
        or not key_id
        or not isinstance(public_key, str)
        for key_id, public_key in key_payload.items()
    ):
        raise ValueError("受信签名密钥字段非法")
    if any(
        not isinstance(approval_payload[name], str)
        or not approval_payload[name]
        for name in approval_fields
    ):
        raise ValueError("批准记录字段必须是非空字符串")
    keys = {
        key_id: b64decode(public_key, validate=True)
        for key_id, public_key in key_payload.items()
    }
    if any(len(public_key) != 32 for public_key in keys.values()):
        raise ValueError("Ed25519 公钥必须是 32 字节")
    approved = ApprovedArtifact(
        model_name=approval_payload["model_name"],
        model_version=approval_payload["model_version"],
        package_sha256=approval_payload["package_sha256"],
        signer_key_id=approval_payload["signer_key_id"],
        approval_state=approval_payload["approval_state"],
    )
    verifier = ModelPackageVerifier(Ed25519SignatureVerifier(keys))
    package = verifier.verify(package_root, approved)
    return dict(package.verification_report)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="验证可信模型包")
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--approval", required=True, type=Path)
    parser.add_argument("--trusted-keys", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = verify_from_files(
            args.package,
            args.approval,
            args.trusted_keys,
        )
        exit_code = 0
    except PluginError as error:
        report = {
            "status": "REJECTED",
            "error": error.info.to_mapping(),
        }
        exit_code = 2
    except Exception as error:
        report = {
            "status": "REJECTED",
            "error": {
                "code": "INPUT_INVALID",
                "stage": "artifact_verification",
                "message": "模型包验证输入无法安全解析",
                "retryable": False,
                "details": {
                    "exception_type": type(error).__name__,
                },
            },
        }
        exit_code = 2
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return exit_code


def _object(path: Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
