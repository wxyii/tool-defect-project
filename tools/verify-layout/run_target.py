#!/usr/bin/env python3
"""执行统一测试入口；未实现或缺工具时明确失败。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def run(command: list[str], cwd: Path = ROOT) -> int:
    print("+", " ".join(command))
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(command, cwd=cwd, env=environment, check=False).returncode


def python_for(base: Path) -> str:
    local = base / ".venv/bin/python"
    root = ROOT / ".venv/bin/python"
    if local.exists():
        return str(local)
    if root.exists():
        return str(root)
    return sys.executable


def unittest_directory(path: Path) -> int:
    tests = sorted(path.rglob("test_*.py")) if path.is_dir() else []
    if not tests:
        print(f"统一入口失败：没有可执行测试：{path.relative_to(ROOT)}", file=sys.stderr)
        return 2
    return run([python_for(path.parent), "-m", "unittest", "discover", "-s", str(path)])


def main() -> int:
    if len(sys.argv) != 2:
        print("用法：run_target.py TARGET", file=sys.stderr)
        return 2
    target = sys.argv[1]

    if target == "test-core":
        return run(
            [python_for(ROOT), "-m", "unittest", "discover", "-s", "tests"],
            ROOT,
        )
    if target == "test-edge":
        return unittest_directory(ROOT / "apps/edge-agent/tests")
    if target == "test-inference":
        return unittest_directory(ROOT / "services/inference-service/tests")
    if target == "test-backend":
        if shutil.which("mvn") is None:
            print("统一入口失败：Maven 未安装。", file=sys.stderr)
            return 2
        return run(["mvn", "-B", "-f", "services/business-api/pom.xml", "test"])
    if target == "test-web":
        package = ROOT / "apps/web-console/package.json"
        if not package.is_file():
            print("统一入口失败：P2 前端 package.json 尚未实现。", file=sys.stderr)
            return 2
        content = json.loads(package.read_text(encoding="utf-8"))
        scripts = content.get("scripts", {})
        required_scripts = ("typecheck", "test", "build")
        missing_scripts = [
            script for script in required_scripts if script not in scripts
        ]
        if missing_scripts:
            print(
                f"统一入口失败：前端缺少脚本：{', '.join(missing_scripts)}。",
                file=sys.stderr,
            )
            return 2
        if shutil.which("pnpm") is None:
            print("统一入口失败：pnpm 未安装。", file=sys.stderr)
            return 2
        expected_pnpm = str(content.get("packageManager", "")).removeprefix(
            "pnpm@"
        )
        actual = subprocess.run(
            ["pnpm", "--version"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if (
            actual.returncode != 0
            or not expected_pnpm
            or actual.stdout.strip() != expected_pnpm
        ):
            print(
                "统一入口失败：pnpm 版本不匹配；"
                f"需要 {expected_pnpm or '清单锁定版本'}，"
                f"实际 {actual.stdout.strip() or '无法读取'}。",
                file=sys.stderr,
            )
            return 2
        for script in required_scripts:
            result = run(
                ["pnpm", "--dir", "apps/web-console", script],
                ROOT,
            )
            if result != 0:
                return result
        return 0

    directory_targets = {
        "test-integration": ROOT / "tests/integration",
        "test-e2e": ROOT / "tests/end-to-end",
        "test-faults": ROOT / "tests/faults",
        "test-performance": ROOT / "tests/performance",
    }
    if target in directory_targets:
        return unittest_directory(directory_targets[target])

    external_targets = {
        "verify-data": ROOT / "tools/verify-data/verify_data.py",
        "verify-models": ROOT / "tools/verify-artifacts/verify_artifacts.py",
    }
    if target in external_targets:
        script = external_targets[target]
        if not script.is_file():
            print(f"统一入口失败：实现尚不存在：{script.relative_to(ROOT)}", file=sys.stderr)
            return 2
        return run([python_for(ROOT), str(script)])

    print(f"未知统一入口：{target}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
