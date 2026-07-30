#!/usr/bin/env python3
"""校验 P1 单仓骨架、所有权、禁止文件和依赖边界。"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DIRECTORIES = (
    "contracts/openapi",
    "contracts/asyncapi",
    "contracts/json-schema",
    "contracts/examples",
    "apps/edge-agent",
    "apps/web-console",
    "services/business-api",
    "services/inference-service",
    "packages/tool-defect-core",
    "packages/python-contracts",
    "packages/java-contracts",
    "packages/typescript-contracts",
    "jobs/dataset-builder",
    "jobs/training-pipeline",
    "jobs/model-evaluator",
    "jobs/artifact-migrator",
    "database",
    "deploy/compose",
    "deploy/environments/development",
    "tools/generate-contracts",
    "tools/verify-contracts",
    "tools/security",
    "tools/sbom",
)
EXPECTED_FILES = (
    "AGENTS.md",
    ".github/CODEOWNERS",
    "Makefile",
    "apps/edge-agent/pyproject.toml",
    "services/business-api/pom.xml",
    "services/inference-service/pyproject.toml",
    "packages/tool-defect-core/README.md",
)
MAKE_TARGETS = (
    "verify-layout",
    "verify-contracts",
    "test-core",
    "test-edge",
    "test-inference",
    "test-backend",
    "test-web",
    "test-integration",
    "test-e2e",
    "test-faults",
    "test-security",
    "test-performance",
    "verify-data",
    "verify-models",
    "verify-all",
)
IGNORED_PARTS = {".git", ".venv", "node_modules", "target", ".pytest_cache", "__pycache__"}
FORBIDDEN_SUFFIXES = {
    ".h5",
    ".hdf5",
    ".keras",
    ".ckpt",
    ".pt",
    ".pth",
    ".onnx",
    ".pb",
    ".tflite",
    ".safetensors",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
}


def git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Git 命令失败")
    return [line for line in result.stdout.splitlines() if line]


def source_files(base: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not base.exists():
        return []
    return sorted(
        path
        for path in base.rglob("*")
        if path.is_file()
        and path.suffix.lower() in suffixes
        and not any(part in IGNORED_PARTS for part in path.parts)
    )


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    for relative in EXPECTED_DIRECTORIES:
        if not (ROOT / relative).is_dir():
            errors.append(f"缺少目标目录：{relative}")
    for relative in EXPECTED_FILES:
        if not (ROOT / relative).is_file():
            errors.append(f"缺少必需文件：{relative}")

    if not (ROOT / "src/tool_defect").is_dir():
        errors.append("现有 src/tool_defect 核心被移动或缺失")
    if not (ROOT / "tests/test_cli.py").is_file():
        errors.append("现有 Python 测试基线缺失")

    makefile = ROOT / "Makefile"
    if makefile.is_file():
        make_text = makefile.read_text(encoding="utf-8")
        for target in MAKE_TARGETS:
            if not re.search(rf"(?m)^{re.escape(target)}\s*:", make_text):
                errors.append(f"Makefile 缺少统一入口：{target}")
        verify_all = re.search(
            r"(?ms)^verify-all\s*:(.*?)(?=^\S[^\n]*:|\Z)",
            make_text,
        )
        if verify_all is not None:
            prerequisites = set(
                re.findall(r"[a-z][a-z0-9-]+", verify_all.group(1))
            )
            required_current = {
                "verify-p1-strict",
                "verify-data",
                "test-core",
                "test-edge",
                "test-inference",
                "test-backend",
                "test-web",
                "test-integration",
                "test-e2e",
                "test-security",
                "verify-models",
            }
            missing_current = required_current - prerequisites
            if missing_current:
                errors.append(
                    "verify-all 缺少当前 P0–P4 门禁："
                    f"{sorted(missing_current)}"
                )
            future_targets = {
                "test-faults",
                "test-performance",
            }
            premature = future_targets & prerequisites
            if premature:
                errors.append(
                    "verify-all 提前包含 P5/P7 门禁："
                    f"{sorted(premature)}"
                )

    gitignore = ROOT / ".gitignore"
    if gitignore.is_file():
        ignore_text = gitignore.read_text(encoding="utf-8")
        for required in ("data/images/", "outputs/*", "*.h5", ".env", "*.pem", "node_modules/"):
            if required not in ignore_text:
                errors.append(f".gitignore 缺少规则：{required}")

    try:
        tracked = git_lines("ls-files")
        tracked_top = set(git_lines("ls-tree", "-d", "--name-only", "HEAD"))
    except RuntimeError as exc:
        errors.append(str(exc))
        tracked = []
        tracked_top = set()

    for relative in tracked:
        path = Path(relative)
        lowered = relative.lower()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"Git 跟踪了禁止制品或密钥：{relative}")
        if lowered.startswith(("data/images/", "data/processed/")):
            errors.append(f"Git 跟踪了原图或生成数据：{relative}")
        if lowered.startswith("outputs/") and relative != "outputs/.gitkeep":
            errors.append(f"Git 跟踪了运行输出：{relative}")
        if path.name.startswith(".env") and not path.name.endswith(".example"):
            errors.append(f"Git 跟踪了环境密钥文件：{relative}")

    legacy_data = [p for p in tracked if p.startswith(("data/manifests/", "data/masks/"))]
    if len(legacy_data) > 183:
        errors.append("迁移前冻结数据基线被扩充；data/manifests 与 data/masks 不得新增文件")
    if legacy_data:
        warnings.append(
            f"保留 {len(legacy_data)} 个迁移前冻结数据文件；完成 P6 注册前不得扩充或删除"
        )

    if "docs" in tracked_top and "Docs" not in tracked_top:
        warnings.append("Git 索引仍使用 docs 小写；大小写敏感 CI 前需由协调任务执行纯大小写重命名")

    forbidden_patterns = (
        (
            ROOT / "services/business-api",
            (".java", ".kt"),
            re.compile(r"(?im)^\s*import\s+(?:tool_defect|inference_service|edge_agent)\b"),
            "业务后端导入了 Python 或推理实现",
        ),
        (
            ROOT / "services/inference-service",
            (".py",),
            re.compile(r"(?im)^\s*(?:from|import)\s+(?:psycopg|sqlalchemy|asyncpg)\b|jdbc:postgresql"),
            "推理服务出现业务数据库依赖",
        ),
        (
            ROOT / "apps/web-console",
            (".ts", ".tsx", ".js", ".vue"),
            re.compile(
                r"(?i)(?:business[_-]?disposition|final[_-]?disposition)\s*"
                r"(?:=|===|:)\s*['\"](?:PASS|FAIL)['\"]"
            ),
            "前端出现最终处置规则",
        ),
    )
    for base, suffixes, pattern, message in forbidden_patterns:
        for path in source_files(base, suffixes):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(text):
                errors.append(f"{message}：{path.relative_to(ROOT)}")

    for base in (ROOT / "contracts", ROOT / "packages"):
        for path in source_files(base, (".json", ".yaml", ".yml", ".py", ".java", ".ts")):
            if path == ROOT / "contracts/examples/invalid/cases-v1.json":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"(?:/Users/|[A-Za-z]:\\\\Users\\\\)", text):
                errors.append(f"契约或生成物包含个人绝对路径：{path.relative_to(ROOT)}")

    for path in ROOT.iterdir():
        if path.is_symlink():
            errors.append(f"根目录不允许以符号链接伪装模块：{path.name}")

    if errors:
        print("仓库布局校验失败：")
        for error in errors:
            print(f"  - {error}")
        if warnings:
            print("警告：")
            for warning in warnings:
                print(f"  - {warning}")
        return 1

    print("仓库布局校验通过。")
    for warning in warnings:
        print(f"警告：{warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
