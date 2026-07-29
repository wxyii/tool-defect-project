#!/usr/bin/env python3
"""标准库静态检查开发 Compose 的镜像固定与密钥注入。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/compose/development.yml"


def main() -> int:
    text = COMPOSE.read_text(encoding="utf-8")
    errors: list[str] = []
    images = re.findall(r"(?m)^\s+image:\s*(\S+)\s*$", text)
    if len(images) < 6:
        errors.append("开发环境缺少基础设施或可观测镜像")
    for image in images:
        final = image.rsplit("/", 1)[-1]
        if ":" not in final or final.endswith(":latest"):
            errors.append(f"镜像未固定非 latest 标签：{image}")
        if "${" in image:
            errors.append(f"镜像版本不得由环境漂移：{image}")
    required_secrets = {
        "POSTGRES_PASSWORD",
        "RABBITMQ_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "GRAFANA_ADMIN_USER",
        "GRAFANA_ADMIN_PASSWORD",
    }
    injected = set(re.findall(r"\$\{([A-Z0-9_]+):\?[^}]+\}", text))
    missing = required_secrets - injected
    if missing:
        errors.append(f"密钥未使用必填环境注入：{sorted(missing)}")
    if re.search(r"(?im)^\s*(?:password|secret|token):\s*[A-Za-z0-9]", text):
        errors.append("Compose 包含明文密钥")
    if errors:
        print("Compose 静态检查失败：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Compose 静态检查通过：{len(images)} 个固定版本镜像，密钥均强制注入")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
