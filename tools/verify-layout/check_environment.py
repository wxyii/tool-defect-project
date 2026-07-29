#!/usr/bin/env python3
"""检查源码门禁或严格门禁所需工具；缺失项必须返回失败。"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run_version(command: list[str]) -> tuple[bool, str]:
    executable = shutil.which(command[0])
    if executable is None:
        return False, "未安装"
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    first = result.stdout.strip().splitlines()
    return result.returncode == 0, first[0] if first else "无法读取版本"


def major(text: str) -> int | None:
    match = re.search(r"(?<!\d)(\d+)(?:\.\d+)+", text)
    return int(match.group(1)) if match else None


def main() -> int:
    profile = "strict"
    if len(sys.argv) == 2:
        profile = sys.argv[1]
    if profile not in {"source", "strict"}:
        print("用法：check_environment.py [source|strict]", file=sys.stderr)
        return 2

    checks: list[tuple[str, bool, str]] = []
    python_path = ROOT / ".venv/bin/python"
    python_command = [str(python_path if python_path.exists() else Path(sys.executable)), "--version"]
    ok, version = run_version(python_command)
    checks.append(("Python 3.11", ok and major(version) == 3 and "3.11" in version, version))

    for label, command, required_major in (
        ("uv", ["uv", "--version"], None),
        ("GNU Make", ["make", "--version"], None),
        ("Git", ["git", "--version"], None),
        ("Java", ["java", "-version"], 25),
        ("javac", ["javac", "-version"], 25),
    ):
        ok, version = run_version(command)
        checks.append((label, ok and (required_major is None or major(version) == required_major), version))

    if profile == "strict":
        for label, command, minimum_major in (
            ("Maven", ["mvn", "--version"], 3),
            ("npm", ["npm", "--version"], 10),
            ("Docker", ["docker", "--version"], 24),
            ("Docker Compose", ["docker", "compose", "version"], 2),
        ):
            ok, version = run_version(command)
            version_major = major(version)
            checks.append(
                (
                    label,
                    ok and version_major is not None and version_major >= minimum_major,
                    version,
                )
            )
        ok, version = run_version(["node", "--version"])
        checks.append(("Node.js 20.13.1", ok and version.lstrip("v") == "20.13.1", version))
        ok, version = run_version(["pnpm", "--version"])
        checks.append(("pnpm 10.34.5", ok and version == "10.34.5", version))

        tsc = ROOT / "packages/typescript-contracts/node_modules/.bin/tsc"
        if tsc.exists():
            ok, version = run_version([str(tsc), "--version"])
        else:
            ok, version = run_version(["tsc", "--version"])
        checks.append(("TypeScript 编译器", ok, version))

    failed = False
    print(f"环境前置检查（{profile}）：")
    for label, ok, version in checks:
        state = "通过" if ok else "失败"
        print(f"  {state:2s}  {label}: {version}")
        failed = failed or not ok
    if failed:
        print("环境前置条件不满足；严格验证不得标记为通过。")
        return 1
    print("环境前置条件满足。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
