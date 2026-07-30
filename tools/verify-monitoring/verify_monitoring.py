#!/usr/bin/env python3
"""P5 监控资产的离线确定性门禁。"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
MONITORING = ROOT / "deploy/monitoring"
MANIFEST = MONITORING / "monitoring-manifest.json"


def main() -> int:
    errors: list[str] = []
    manifest = load_json(MANIFEST, errors)
    if not isinstance(manifest, dict):
        return report(errors or ["监控清单必须是 JSON 对象"])

    required_dashboards = set(manifest.get("dashboards", []))
    actual_dashboards: dict[str, dict[str, object]] = {}
    for path in sorted(
        (MONITORING / "grafana/dashboards").glob("*.json")
    ):
        value = load_json(path, errors)
        if not isinstance(value, dict):
            continue
        uid = value.get("uid")
        if not isinstance(uid, str) or not uid:
            errors.append(f"看板缺少稳定 uid：{relative(path)}")
            continue
        if uid in actual_dashboards:
            errors.append(f"看板 uid 重复：{uid}")
        actual_dashboards[uid] = value
        if not isinstance(value.get("time"), dict):
            errors.append(f"看板缺少明确时间范围：{uid}")
        templating = value.get("templating")
        variables = {
            item.get("name")
            for item in (
                templating.get("list", [])
                if isinstance(templating, dict)
                else []
            )
            if isinstance(item, dict)
        }
        if "environment" not in variables:
            errors.append(f"看板缺少环境筛选：{uid}")

    missing_dashboards = required_dashboards - set(actual_dashboards)
    extra_dashboards = set(actual_dashboards) - required_dashboards
    if missing_dashboards:
        errors.append(f"缺少看板：{sorted(missing_dashboards)}")
    if extra_dashboards:
        errors.append(f"存在未登记看板：{sorted(extra_dashboards)}")

    quality = actual_dashboards.get("quality-review", {})
    quality_text = json.dumps(quality, ensure_ascii=False)
    for required in ("样本量", "时间范围", "真值来源", "truth_source"):
        if required not in quality_text:
            errors.append(f"质量看板缺少统计语境：{required}")

    alerts = read_text(MONITORING / "alerts.yml", errors)
    declared_alerts = set(
        re.findall(r"^\s*-\s+alert:\s*([A-Za-z0-9_]+)\s*$", alerts, re.M)
    )
    required_alerts = set(manifest.get("required_alerts", []))
    if required_alerts - declared_alerts:
        errors.append(
            f"缺少必需告警：{sorted(required_alerts - declared_alerts)}"
        )
    for alert in declared_alerts:
        block = _yaml_rule_block(alerts, alert)
        if "severity:" not in block:
            errors.append(f"告警缺少严重度：{alert}")
        if "runbook:" not in block:
            errors.append(f"告警缺少运行手册：{alert}")
        else:
            runbook = re.search(r"(?m)^\s*runbook:\s*([a-z0-9-]+)\s*$", block)
            if runbook is None or not (
                ROOT / "Docs/runbooks" / f"{runbook.group(1)}.md"
            ).is_file():
                errors.append(f"告警运行手册不存在：{alert}")
        if "for:" not in block:
            errors.append(f"告警缺少持续时间：{alert}")

    prometheus = read_text(MONITORING / "prometheus.yml", errors)
    if "rule_files:" not in prometheus or "tool-defect.yml" not in (
        read_text(
            ROOT / "deploy/compose/development.yml",
            errors,
        )
    ):
        errors.append("Prometheus 未加载 P5 告警规则")

    collector = read_text(MONITORING / "otel-collector.yml", errors)
    for fragment in (
        "tail_sampling:",
        "status_codes: [ERROR]",
        "type: latency",
        "otlp/tempo:",
        "otlphttp/loki:",
        "retry_on_failure:",
        "logs:",
        "traces:",
        "metrics:",
    ):
        if fragment not in collector:
            errors.append(f"遥测收集器缺少配置：{fragment}")

    forbidden_labels = set(manifest.get("forbidden_labels", []))
    monitoring_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(MONITORING.rglob("*"))
        if path.is_file()
    )
    for grouped in re.findall(
        r"\b(?:by|without)\s*\(([^)]*)\)",
        monitoring_text,
    ):
        labels = {
            value.strip()
            for value in grouped.split(",")
            if value.strip()
        }
        illegal = labels & forbidden_labels
        if illegal:
            errors.append(
                f"指标聚合使用高基数标签：{sorted(illegal)}"
            )

    objectives = manifest.get("service_objectives")
    if not isinstance(objectives, list) or len(objectives) < 6:
        errors.append("服务目标计算清单不完整")
    else:
        for objective in objectives:
            if not isinstance(objective, dict):
                errors.append("服务目标条目必须是对象")
                continue
            target = objective.get("target")
            if not isinstance(target, str) or not target.startswith("PENDING_"):
                errors.append(
                    "现场目标尚未签字时必须显式标为 PENDING"
                )

    for path in (
        MONITORING / "loki.yml",
        MONITORING / "tempo.yml",
        MONITORING
        / "grafana/provisioning/datasources/datasources.yml",
        MONITORING
        / "grafana/provisioning/dashboards/dashboards.yml",
    ):
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            errors.append(f"监控后端配置缺失：{relative(path)}")

    source_evidence = {
        ROOT
        / "apps/edge-agent/src/edge_agent/capture/coordinator.py": (
            "tool_defect_edge_captures_total",
        ),
        ROOT
        / "apps/edge-agent/src/edge_agent/health/heartbeat.py": (
            "tool_defect_edge_queue_depth",
            "tool_defect_edge_oldest_task_age_seconds",
            "tool_defect_edge_disk_usage_ratio",
            "tool_defect_edge_device_online",
        ),
        ROOT
        / (
            "services/inference-service/src/inference_service/"
            "orchestration/pipeline.py"
        ): (
            "tool_defect_inference_stage_duration_seconds",
            "tool_defect_inference_requests_total",
        ),
        ROOT
        / "services/inference-service/src/inference_service/api/health.py": (
            "tool_defect_inference_ready",
        ),
        ROOT
        / (
            "services/business-api/src/main/java/com/tooldefect/business/"
            "shared/infrastructure/OperationalMetrics.java"
        ): (
            "tool.defect.database.writable",
            "tool.defect.queue.ready.messages",
            "tool.defect.queue.dead.letter.messages",
            "tool.defect.storage.orphan.objects",
            "tool.defect.integrity.conflicts",
            "tool.defect.review.pending.tasks",
            "tool.defect.quality.reviewed.samples.30d",
            "tool.defect.dataset.candidates",
            "tool.defect.training.active.runs",
            "tool.defect.model.production.deployments",
        ),
    }
    for path, fragments in source_evidence.items():
        source = read_text(path, errors)
        for fragment in fragments:
            if fragment not in source:
                errors.append(
                    f"核心看板指标没有服务端来源：{fragment}"
                )

    return report(errors)


def _yaml_rule_block(body: str, alert: str) -> str:
    match = re.search(
        rf"^\s*-\s+alert:\s*{re.escape(alert)}\s*$",
        body,
        re.M,
    )
    if match is None:
        return ""
    next_rule = re.search(r"^\s*-\s+alert:\s*", body[match.end():], re.M)
    end = (
        match.end() + next_rule.start()
        if next_rule is not None
        else len(body)
    )
    return body[match.start():end]


def load_json(path: Path, errors: list[str]) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"JSON 无法读取：{relative(path)}：{error}")
        return None


def read_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        errors.append(f"文件无法读取：{relative(path)}：{error}")
        return ""


def relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def report(errors: list[str]) -> int:
    if errors:
        for error in errors:
            print(f"错误：{error}", file=sys.stderr)
        return 1
    print("P5 监控、五类看板、服务目标和分级告警：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
