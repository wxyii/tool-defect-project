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


def run(
    command: list[str],
    cwd: Path = ROOT,
    environment_overrides: dict[str, str] | None = None,
) -> int:
    print("+", " ".join(command))
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if environment_overrides:
        environment.update(environment_overrides)
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
    strict_runner = ROOT / "tools/verify-layout/strict_unittest.py"
    if not strict_runner.is_file():
        print("统一入口失败：严格 unittest 执行器不存在。", file=sys.stderr)
        return 2
    return run([python_for(path.parent), str(strict_runner), str(path)])


def executable_candidates(name: str) -> list[Path]:
    candidates: list[Path] = []
    resolved = shutil.which(name)
    if resolved:
        candidates.append(Path(resolved))
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if directory:
            candidate = Path(directory) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                candidates.append(candidate)
    return list(dict.fromkeys(path.resolve() for path in candidates))


def node_with_version(expected: str) -> Path | None:
    configured = os.environ.get("TOOL_DEFECT_NODE")
    candidates = [Path(configured)] if configured else []
    candidates.extend(executable_candidates("node"))
    for candidate in candidates:
        result = subprocess.run(
            [str(candidate), "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip().lstrip("v") == expected:
            return candidate
    return None


def pnpm_with_version(node: Path, expected: str) -> list[str] | None:
    configured = os.environ.get("TOOL_DEFECT_PNPM")
    candidates: list[Path] = [Path(configured)] if configured else []
    candidates.extend(executable_candidates("pnpm"))
    npm_cache = Path.home() / ".npm/_npx"
    if npm_cache.is_dir():
        for package in npm_cache.glob("*/node_modules/pnpm/package.json"):
            try:
                metadata = json.loads(package.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if metadata.get("version") == expected:
                candidates.extend(
                    (
                        package.parent / "bin/pnpm.cjs",
                        package.parent / "bin/pnpm.mjs",
                    )
                )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        command = (
            [str(node), str(candidate)]
            if candidate.suffix in {".cjs", ".mjs", ".js"}
            else [str(candidate)]
        )
        result = subprocess.run(
            [*command, "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == expected:
            return command
    return None


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
        wrapper = ROOT / "services/business-api/mvnw"
        if not wrapper.is_file() or not os.access(wrapper, os.X_OK):
            print("统一入口失败：Maven Wrapper 不存在或不可执行。", file=sys.stderr)
            return 2
        maven_user_home = Path(
            os.environ.get(
                "MAVEN_USER_HOME",
                str(ROOT / ".build/maven-user-home"),
            )
        ).resolve()
        maven_repository = Path(
            os.environ.get(
                "TOOL_DEFECT_MAVEN_REPO",
                str(ROOT / ".build/maven-repository"),
            )
        ).resolve()
        return run(
            [
                str(wrapper),
                "-B",
                f"-Dmaven.repo.local={maven_repository}",
                "-f",
                "services/business-api/pom.xml",
                "verify",
            ],
            environment_overrides={
                "MAVEN_USER_HOME": str(maven_user_home),
            },
        )
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
        expected_node = str(content.get("engines", {}).get("node", ""))
        expected_pnpm = str(content.get("packageManager", "")).removeprefix(
            "pnpm@"
        )
        node = node_with_version(expected_node)
        if node is None:
            print(
                f"统一入口失败：需要精确 Node.js {expected_node or '清单版本'}。",
                file=sys.stderr,
            )
            return 2
        pnpm = pnpm_with_version(node, expected_pnpm)
        if pnpm is None:
            print(
                f"统一入口失败：需要精确 pnpm {expected_pnpm or '清单版本'}。",
                file=sys.stderr,
            )
            return 2
        for script in required_scripts:
            result = run(
                [*pnpm, "--dir", "apps/web-console", script],
                ROOT,
            )
            if result != 0:
                return result
        return 0

    directory_targets = {
        "test-integration": ROOT / "tests/integration",
        "test-e2e": ROOT / "tests/end-to-end",
        "test-faults": ROOT / "tests/faults",
        "test-security": ROOT / "tests/security",
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
