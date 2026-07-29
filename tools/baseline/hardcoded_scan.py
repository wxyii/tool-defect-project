#!/usr/bin/env python3
"""扫描生产代码中未登记的现场参数硬编码。

旧 ``app/legacy`` 和离线算法核心不属于生产实现，因此不在扫描范围。
配置文件、生成代码、测试和样例也不扫描。扫描只报告命中，不修改源码。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


PRODUCTION_ROOTS = (
    "apps/edge-agent",
    "apps/web-console",
    "services/business-api",
    "services/inference-service",
)

SOURCE_SUFFIXES = {".py", ".java", ".kt", ".ts", ".tsx", ".js", ".vue"}

SITE_PARAMETER_NAMES = (
    "automatic_pass_threshold",
    "qualification_threshold",
    "confidence_threshold",
    "cycle_time_ms",
    "allowed_latency_ms",
    "maximum_offline_hours",
    "offline_duration_hours",
    "local_disk_capacity_gb",
    "disk_capacity_gb",
    "review_sla_minutes",
    "retention_days",
    "rpo_minutes",
    "rto_minutes",
    "presigned_url_ttl_seconds",
    "heartbeat_timeout_seconds",
    "camera_model",
    "plc_protocol",
    "identity_provider",
    "object_storage_product",
)

ASSIGNMENT_PATTERN = re.compile(
    rf"\b(?P<name>{'|'.join(map(re.escape, SITE_PARAMETER_NAMES))})\b"
    r"\s*(?::[^=\n]+)?=\s*"
    r"(?P<literal>-?\d+(?:\.\d+)?|true|false|null|None|"
    r"\"[^\"\n]*\"|'[^'\n]*')",
    re.IGNORECASE,
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _excluded(relative: Path) -> bool:
    lowered = {part.lower() for part in relative.parts}
    return bool(
        lowered
        & {
            "test",
            "tests",
            "fixtures",
            "examples",
            "generated",
            "node_modules",
            "target",
            "dist",
            "build",
        }
    )


def scan_hardcoded_site_parameters(root: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for production_root in PRODUCTION_ROOTS:
        base = root / production_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if (
                not path.is_file()
                or path.suffix.lower() not in SOURCE_SUFFIXES
                or _excluded(path.relative_to(root))
            ):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                stripped = line.strip()
                if (
                    not stripped
                    or stripped.startswith(("#", "//", "*"))
                ):
                    continue
                for match in ASSIGNMENT_PATTERN.finditer(line):
                    findings.append(
                        {
                            "path": path.relative_to(root).as_posix(),
                            "line": line_number,
                            "parameter": match.group("name"),
                            "literal": match.group("literal"),
                        }
                    )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repository_root(),
    )
    args = parser.parse_args(argv)
    findings = scan_hardcoded_site_parameters(args.repo_root.resolve())
    print(
        json.dumps(
            {"valid": not findings, "findings": findings},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
