#!/usr/bin/env python3
"""R9 模型供应链门禁包装器。

先运行已有的真实模型包验证器；没有外部模型包证据时明确返回 HOLD，
不以单元测试或缺省参数冒充生产供应链通过。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "jobs/model-supply/verify_model_supply.py"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def main() -> int:
    names = (
        "TD_MODEL_ARCHIVE",
        "TD_MODEL_DECLARED_SIZE",
        "TD_MODEL_DECLARED_SHA256",
        "TD_MODEL_TRUSTED_KEYS",
    )
    values = {name: os.environ.get(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        _print(
            {
                "status": "HOLD",
                "error_code": "MODEL_SUPPLY_EVIDENCE_MISSING",
                "message": "缺少外部模型包供应链证据，未执行生产模型通过判定",
                "missing": missing,
            }
        )
        return 2

    try:
        declared_size = int(values["TD_MODEL_DECLARED_SIZE"])
    except ValueError:
        _print(
            {
                "status": "HOLD",
                "error_code": "MODEL_SUPPLY_SIZE_INVALID",
                "message": "模型包声明大小不是有效整数",
            }
        )
        return 2
    if declared_size <= 0 or not SHA256.fullmatch(values["TD_MODEL_DECLARED_SHA256"]):
        _print(
            {
                "status": "HOLD",
                "error_code": "MODEL_SUPPLY_DECLARATION_INVALID",
                "message": "模型包声明大小或 SHA-256 格式无效",
            }
        )
        return 2

    command = [
        sys.executable,
        str(VERIFY),
        "--archive",
        values["TD_MODEL_ARCHIVE"],
        "--declared-size",
        str(declared_size),
        "--declared-sha256",
        values["TD_MODEL_DECLARED_SHA256"],
        "--trusted-keys",
        values["TD_MODEL_TRUSTED_KEYS"],
    ]
    policy = os.environ.get("TD_MODEL_POLICY", "").strip()
    if policy:
        command.extend(("--policy", policy))
    completed = subprocess.run(command, cwd=ROOT, check=False)
    return completed.returncode


def _print(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    raise SystemExit(main())
