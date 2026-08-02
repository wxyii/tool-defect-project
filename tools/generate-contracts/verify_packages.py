#!/usr/bin/env python3
"""在临时目录编译三语言契约包，不污染工作树。"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def compile_python(temp: Path) -> None:
    sources = sorted(
        (ROOT / "packages/python-contracts/src/tool_defect_contracts").rglob("*.py")
    )
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(temp / "pycache")
    run([sys.executable, "-m", "py_compile", *map(str, sources)], env)


def compile_java(temp: Path) -> None:
    javac = shutil.which("javac")
    if not javac:
        raise RuntimeError("缺少 javac，无法验证 Java 生成物")
    sources = sorted((ROOT / "packages/java-contracts/src/main/java").rglob("*.java"))
    run([javac, "-Xlint:all", "-Werror", "-d", str(temp / "classes"), *map(str, sources)])


def compile_typescript() -> None:
    local = ROOT / "packages/typescript-contracts/node_modules/.bin/tsc"
    tsc = str(local) if local.exists() else shutil.which("tsc")
    if not tsc:
        raise RuntimeError("缺少 tsc，无法验证 TypeScript 生成物")
    run([tsc, "--project", "packages/typescript-contracts/tsconfig.json", "--noEmit"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--languages",
        choices=("offline", "all"),
        default="all",
        help="offline 只验证当前离线环境具备的 Python 和 Java",
    )
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix="contract-compile-") as directory:
            temp = Path(directory)
            compile_python(temp)
            compile_java(temp)
            if args.languages == "all":
                compile_typescript()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"契约包编译失败：{exc}", file=sys.stderr)
        return 1
    print("契约包编译通过：" + ("Python、Java" if args.languages == "offline" else "Python、Java、TypeScript"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
