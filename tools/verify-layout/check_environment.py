#!/usr/bin/env python3
"""检查源码门禁或严格门禁所需工具；缺失项必须返回失败。"""

from __future__ import annotations

import json
import os
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


def run_matching_version(
    command: list[str],
    expected_line_fragment: str,
    environment_overrides: dict[str, str] | None = None,
) -> tuple[bool, str]:
    executable = shutil.which(command[0])
    if executable is None:
        return False, "未安装"
    environment = os.environ.copy()
    if environment_overrides:
        environment.update(environment_overrides)
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    lines = result.stdout.strip().splitlines()
    matched = next(
        (
            line
            for line in lines
            if line == expected_line_fragment
            or line.startswith(f"{expected_line_fragment} ")
        ),
        None,
    )
    display = matched or (lines[0] if lines else "无法读取版本")
    return result.returncode == 0 and matched is not None, display


def major(text: str) -> int | None:
    match = re.search(r"(?<!\d)(\d+)(?:\.\d+)+", text)
    return int(match.group(1)) if match else None


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


def node_with_version(expected: str) -> tuple[Path | None, str]:
    configured = os.environ.get("TOOL_DEFECT_NODE")
    candidates = [Path(configured)] if configured else []
    candidates.extend(executable_candidates("node"))
    for candidate in candidates:
        ok, version = run_version([str(candidate), "--version"])
        if ok and version.lstrip("v") == expected:
            return candidate, version
    return None, f"未找到精确版本 {expected}"


def pnpm_with_version(
    node: Path,
    expected: str,
) -> tuple[list[str] | None, str]:
    configured = os.environ.get("TOOL_DEFECT_PNPM")
    candidates = [Path(configured)] if configured else []
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
        ok, version = run_version([*command, "--version"])
        if ok and version == expected:
            return command, version
    return None, f"未找到精确版本 {expected}"


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
        maven_wrapper = ROOT / "services/business-api/mvnw"
        ok, version = run_matching_version(
            [str(maven_wrapper), "--version"],
            "Apache Maven 3.9.15",
            {
                "MAVEN_USER_HOME": os.environ.get(
                    "MAVEN_USER_HOME",
                    str(ROOT / ".build/maven-user-home"),
                ),
            },
        )
        checks.append(
            (
                "Maven Wrapper 3.9.15",
                ok,
                version,
            )
        )

        for label, command, minimum_major in (
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
        web_package = json.loads(
            (ROOT / "apps/web-console/package.json").read_text(encoding="utf-8")
        )
        expected_node = str(web_package["engines"]["node"])
        node, version = node_with_version(expected_node)
        checks.append((f"Node.js {expected_node}", node is not None, version))

        expected_pnpm = str(web_package["packageManager"]).removeprefix("pnpm@")
        if node is None:
            pnpm_command, version = None, "缺少匹配的 Node.js"
        else:
            pnpm_command, version = pnpm_with_version(node, expected_pnpm)
        checks.append((f"pnpm {expected_pnpm}", pnpm_command is not None, version))

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
