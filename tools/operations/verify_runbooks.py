#!/usr/bin/env python3
"""验证 P5 分级运行手册的结构、安全控制和演练记录。"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.operations.runbook_drill import run_isolated_drill
from tools.operations.lifecycle_recovery import RecoveryError

ROOT = PROJECT_ROOT
RUNBOOK_ROOT = ROOT / "Docs/runbooks"
REQUIRED = {
    "01-disk-full.md",
    "02-network-outage.md",
    "03-dead-letter.md",
    "04-database-unwritable.md",
    "05-object-storage.md",
    "06-model-not-ready.md",
    "07-hash-conflict.md",
    "08-review-backlog.md",
    "09-backup-restore.md",
    "10-emergency-rollback.md",
}
SECTIONS = (
    "影响确认",
    "只读检查",
    "恢复步骤",
    "升级路径",
    "恢复验证",
    "危险操作控制",
)
CONTROL_WORDS = ("所需权限", "操作原因", "二次确认", "审计事件")
FORBIDDEN = (
    "rm -rf",
    "curl -k",
    "--no-verify",
    "默认密码",
    "跳过审计",
)


def main() -> int:
    errors: list[str] = []
    actual = {path.name for path in RUNBOOK_ROOT.glob("[0-9][0-9]-*.md")}
    if actual != REQUIRED:
        errors.append(
            f"运行手册集合不完整：缺少={sorted(REQUIRED - actual)}，"
            f"多余={sorted(actual - REQUIRED)}"
        )
    for name in sorted(REQUIRED):
        path = RUNBOOK_ROOT / name
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^严重级别：S[123]$", body):
            errors.append(f"{name} 缺少 S1/S2/S3 严重级别")
        for section in SECTIONS:
            if f"## {section}" not in body:
                errors.append(f"{name} 缺少章节：{section}")
        for word in CONTROL_WORDS:
            if word not in body:
                errors.append(f"{name} 危险操作控制缺少：{word}")
        for forbidden in FORBIDDEN:
            if forbidden in body:
                errors.append(f"{name} 包含禁止操作：{forbidden}")
        if "HOLD" not in body:
            errors.append(f"{name} 未声明未知状态进入 HOLD")

    index = RUNBOOK_ROOT / "README.md"
    if not index.is_file():
        errors.append("缺少运行手册索引")
    else:
        body = index.read_text(encoding="utf-8")
        for name in sorted(REQUIRED):
            if name not in body:
                errors.append(f"运行手册索引缺少：{name}")

    drill_path = RUNBOOK_ROOT / "drill-record.json"
    try:
        drill = json.loads(drill_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"演练记录无法读取：{error}")
    else:
        if drill.get("schema_version") != "tool-defect-runbook-drill/v1":
            errors.append("演练记录模式版本无效")
        if drill.get("environment") != "ISOLATED_TEST":
            errors.append("P5 自动演练必须明确使用隔离测试环境")
        if drill.get("status") != "PASSED_WITH_LIMITATIONS":
            errors.append("演练记录必须保留未完成现场执行限制")
        if not drill.get("duration_seconds"):
            errors.append("演练记录缺少耗时")
        if not drill.get("omissions") or not drill.get("revisions"):
            errors.append("演练记录必须包含遗漏和修订")
        if drill.get("author_is_executor") is not False:
            errors.append("机器执行角色必须与文档作者角色分离")
        try:
            execution = run_isolated_drill()
        except (RuntimeError, RecoveryError) as error:
            errors.append(f"隔离机器演练执行失败：{error}")
        else:
            executed = {
                item.get("name")
                for item in execution.get("scenarios", [])
                if isinstance(item, dict) and item.get("status") == "PASSED"
            }
            recorded = set(drill.get("scenarios", []))
            if execution.get("status") != "PASSED" or executed != recorded:
                errors.append("演练记录与本次隔离机器执行结果不一致")

    if errors:
        print("P5 运行手册门禁失败：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("P5 十类分级运行手册与隔离演练记录：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
