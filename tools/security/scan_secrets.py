#!/usr/bin/env python3
"""扫描源码与配置中的高可信密钥特征。"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {
    ".env",
    ".example",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".properties",
    ".py",
    ".java",
    ".kt",
    ".ts",
    ".tsx",
    ".js",
    ".vue",
    ".md",
    ".sh",
}
SCANNED_ROOTS = {
    "apps",
    "services",
    "packages",
    "jobs",
    "database",
    "deploy",
    "tools",
    "contracts",
    ".github",
}


def candidates() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    paths: list[Path] = []
    for relative in result.stdout.splitlines():
        path = Path(relative)
        if not path.parts or path.parts[0] not in SCANNED_ROOTS:
            continue
        absolute = ROOT / path
        if not absolute.is_file() or absolute.stat().st_size > 2_000_000:
            continue
        if absolute.suffix.lower() in TEXT_SUFFIXES or absolute.name.startswith(".env"):
            paths.append(absolute)
    return sorted(set(paths))


def main() -> int:
    token_patterns = {
        "私钥头": re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "云访问密钥": re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
        "代码托管令牌": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
        "通信平台令牌": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
        "未脱敏 JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    }
    assignment = re.compile(
        r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key)"
        r"\b\s*[:=]\s*[\"']([^\"']{8,})[\"']"
    )
    findings: list[str] = []
    self_path = Path(__file__).resolve()
    for path in candidates():
        if path.resolve() == self_path:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        relative = path.relative_to(ROOT)
        for label, pattern in token_patterns.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{relative}:{line} {label}")
        for match in assignment.finditer(text):
            value = match.group(2).strip()
            if (
                value.startswith("${")
                or value.lower() in {"changeme", "example-only", "not-a-secret"}
                or "example.invalid" in value
                or (
                    "tests" in relative.parts
                    and re.fullmatch(r"[a-z]+(?:-[a-z]+)+", value)
                )
            ):
                continue
            line = text.count("\n", 0, match.start()) + 1
            findings.append(f"{relative}:{line} 疑似明文敏感赋值")
    if findings:
        print("密钥扫描失败：", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print(f"密钥扫描通过：已检查 {len(candidates())} 个源码与配置文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
