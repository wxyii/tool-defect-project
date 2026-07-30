#!/usr/bin/env python3
"""P5 生产身份、网络、机密、容器与供应链安全门禁。"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/compose/production-security-baseline.yml"
NGINX = ROOT / "deploy/gateway/nginx.conf"
SUPPLY_CHAIN = ROOT / "deploy/security/supply-chain-policy.json"
IDENTITY = ROOT / "deploy/security/identity-and-network-policy.json"
SERVICES = {
    "gateway",
    "business-api",
    "inference-service",
    "postgres",
    "rabbitmq",
    "object-storage",
    "telemetry",
}


def main() -> int:
    errors: list[str] = []
    compose = read(COMPOSE, errors)
    hardening = _block(compose, "x-runtime-hardening", top_level=True)
    for fragment in (
        "read_only: true",
        'cap_drop: ["ALL"]',
        "no-new-privileges:true",
        "pids_limit:",
    ):
        if fragment not in hardening:
            errors.append(f"容器加固锚点缺少：{fragment}")

    for service in sorted(SERVICES):
        block = _block(compose, service)
        if not block:
            errors.append(f"生产清单缺少服务：{service}")
            continue
        for fragment in (
            "<<: *runtime-hardening",
            "image:",
            "@sha256:${",
            "user:",
            "mem_limit:",
            "cpus:",
            "networks:",
        ):
            if fragment not in block:
                errors.append(f"{service} 缺少安全基线：{fragment}")
        if re.search(r"(?m)^\s*privileged:\s*true", block):
            errors.append(f"{service} 禁止特权运行")
        if ":latest" in block:
            errors.append(f"{service} 禁止 latest 镜像")

    inference = _block(compose, "inference-service")
    for forbidden in (
        "business_database",
        "TD_DATABASE_",
        "ports:",
        "ingress",
    ):
        if forbidden in inference:
            errors.append(f"推理服务存在禁止的数据库、入口或对外端口：{forbidden}")
    for required in (
        "TD_DISABLE_INTERNET_EGRESS: \"true\"",
        "model-trust-roots.json",
        "inference_queue",
        "object_storage",
        "inference_control",
    ):
        if required not in inference:
            errors.append(f"推理服务缺少最小网络或信任配置：{required}")

    gateway = _block(compose, "gateway")
    if "object_storage" in gateway or "business_database" in gateway:
        errors.append("浏览器入口不得连接对象存储或数据库网络")

    secret_section = _top_level_section(compose, "secrets")
    if "file:" in secret_section:
        errors.append("生产机密必须由外部机密提供者注入，不能引用工作区文件")
    declared_secrets = re.findall(
        r"(?m)^  ([a-z0-9_]+):\s*\{external:\s*true\}",
        secret_section,
    )
    if len(declared_secrets) < 20:
        errors.append("服务、证书、存储和遥测机密未充分分离")

    nginx = read(NGINX, errors)
    for fragment in (
        "ssl_protocols TLSv1.3",
        "ssl_verify_client optional",
        "ssl_crl /run/secrets/device-ca.crl",
        "listen 9443 ssl",
        "ssl_client_certificate /run/secrets/service-ca.crt",
        "ssl_crl /run/secrets/service-ca.crl",
        "ssl_verify_client on",
        "X-Device-Certificate-Fingerprint",
        "X-Service-Certificate-Fingerprint",
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "limit_req",
        "client_max_body_size",
    ):
        if fragment not in nginx:
            errors.append(f"网关缺少安全控制：{fragment}")
    for fragment in (
        "TD_BUSINESS_API_URL: https://gateway:9443",
        "TD_BUSINESS_API_CLIENT_CERTIFICATE:",
        "TD_BUSINESS_API_CLIENT_KEY:",
    ):
        if fragment not in inference:
            errors.append(f"推理回调缺少服务双向 TLS 配置：{fragment}")
    if re.search(r"proxy_pass\s+https?://\\$", nginx):
        errors.append("网关 proxy_pass 不得由请求或变量动态决定")

    supply = load_json(SUPPLY_CHAIN, errors)
    identity = load_json(IDENTITY, errors)
    if isinstance(supply, dict):
        images = supply.get("container_images", {})
        models = supply.get("model_packages", {})
        training = supply.get("training", {})
        if not isinstance(images, dict) or not images.get(
            "mutable_tags_forbidden"
        ):
            errors.append("镜像供应链必须禁止可变标签")
        if not isinstance(images, dict) or set(
            images.get("attestations_required", [])
        ) != {"slsa-provenance", "spdx-sbom", "vulnerability-scan"}:
            errors.append("镜像缺少来源、软件物料清单或漏洞证明要求")
        if not isinstance(models, dict) or models.get(
            "signature_algorithm"
        ) != "ed25519":
            errors.append("模型包必须使用登记的 Ed25519 信任根验签")
        if not isinstance(models, dict) or models.get(
            "verification_result_on_unknown_or_invalid"
        ) != "HOLD":
            errors.append("模型验证未知或失败必须进入 HOLD")
        if not isinstance(training, dict) or training.get(
            "production_alias_write"
        ) is not False:
            errors.append("训练身份不得写生产模型别名")
    if isinstance(identity, dict):
        if identity.get("network_default") != "DENY":
            errors.append("生产网络必须默认拒绝")
        forbidden_paths = set(identity.get("forbidden_paths", []))
        for path in (
            "browser->object-list",
            "inference-service->database",
            "inference-service->internet",
            "training->production-alias",
        ):
            if path not in forbidden_paths:
                errors.append(f"身份网络策略缺少禁止路径：{path}")
        device = identity.get("device_identity", {})
        if not isinstance(device, dict) or not device.get(
            "certificate_per_device"
        ) or not device.get("revocation_list"):
            errors.append("设备身份必须独立并支持证书吊销")

    materializer = read(
        ROOT
        / "services/inference-service/src/inference_service/storage/materializer.py",
        errors,
    )
    for fragment in (
        "(?!https?://)",
        "(?![A-Za-z]:)",
        '".." in self.object_key.split("/")',
        "_file_sha256(destination)",
    ):
        if fragment not in materializer:
            errors.append(f"推理对象读取缺少 SSRF/完整性控制：{fragment}")

    inference_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(
            (ROOT / "services/inference-service/src").rglob("*.py")
        )
    ).lower()
    for forbidden in (
        "psycopg",
        "postgresql://",
        "jdbc:",
        "create_engine(",
    ):
        if forbidden in inference_sources:
            errors.append(f"推理服务不得访问业务数据库：{forbidden}")

    web_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "apps/web-console/src").rglob("*"))
        if path.is_file()
    ).lower()
    for forbidden in (
        "listobjects",
        "listbuckets",
        "aws_access_key",
        "s3_secret",
    ):
        if forbidden in web_sources:
            errors.append(f"浏览器不得列桶或持有长期凭据：{forbidden}")

    return report(errors)


def _block(body: str, name: str, *, top_level: bool = False) -> str:
    indent = "" if top_level else "  "
    pattern = re.compile(
        rf"(?ms)^{re.escape(indent + name)}:\s*(?:&[^\n]+)?\n"
        rf"(.*?)(?=^{re.escape(indent)}[A-Za-z0-9_-]+:\s*(?:&[^\n]+)?\n|\Z)"
    )
    match = pattern.search(body)
    return match.group(0) if match is not None else ""


def _top_level_section(body: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(name)}:\s*\n(.*?)(?=^[A-Za-z0-9_-]+:\s*\n|\Z)",
        body,
    )
    return match.group(0) if match is not None else ""


def load_json(path: Path, errors: list[str]) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"安全策略无法读取：{path.relative_to(ROOT)}：{error}")
        return None


def read(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"安全资产无法读取：{path.relative_to(ROOT)}：{error}")
        return ""


def report(errors: list[str]) -> int:
    if errors:
        print("生产部署安全基线失败：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("生产身份、网络、机密、容器与供应链安全基线：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
