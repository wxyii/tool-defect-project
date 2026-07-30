#!/usr/bin/env python3
"""与运行手册作者输入隔离的确定性机器执行器。"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.operations.alert_drill import active_alerts
from tools.operations.lifecycle_recovery import (
    RecoveryError,
    create_recovery_point,
    restore_recovery_point,
    verify_recovery_point,
)
from tools.operations.resilience import (
    AttemptResult,
    Outcome,
    RetryPolicy,
    execute_bounded,
    simulate_queue,
)


def run_isolated_drill() -> dict[str, object]:
    scenarios: list[dict[str, str]] = []

    retry = execute_bounded(
        lambda _: AttemptResult(False, True, "TEMPORARY"),
        RetryPolicy(3, 100, 500),
    )
    _require(
        retry.status == Outcome.HOLD
        and retry.attempts == 3
        and retry.delays_ms == (100, 200),
        "有界重试演练失败",
    )
    scenarios.append(
        {"name": "bounded-retry-exhaustion", "status": "PASSED"}
    )

    queue = simulate_queue(
        [3, 3, 3, 3, 0, 0],
        service_per_tick=2,
        outage_ticks={1, 2},
    )
    _require(
        queue.submitted == queue.completed
        and queue.lost_results == 0
        and queue.duplicate_results == 0
        and queue.final_backlog == 0,
        "网络积压恢复演练失败",
    )
    scenarios.append(
        {"name": "network-backlog-recovery", "status": "PASSED"}
    )

    healthy = {
        "production_model_ready_instances": 2,
        "dead_letter_messages": 0,
        "edge_disk_usage_ratio": 0.5,
        "database_write_probe": 1,
        "monitoring_last_success_age_seconds": 15,
        "hash_conflicts": 0,
    }
    drills = {
        "ToolDefectProductionModelNotReady": (
            "production_model_ready_instances",
            0,
        ),
        "ToolDefectDeadLetterPresent": ("dead_letter_messages", 1),
        "ToolDefectEdgeDiskCritical": ("edge_disk_usage_ratio", 0.97),
        "ToolDefectDatabaseUnwritable": ("database_write_probe", 0),
        "ToolDefectMonitoringBlind": (
            "monitoring_last_success_age_seconds",
            181,
        ),
        "ToolDefectHashConflict": ("hash_conflicts", 1),
    }
    for alert, (metric, value) in drills.items():
        fault = dict(healthy)
        fault[metric] = value
        _require(alert in active_alerts(fault), f"告警未触发：{alert}")
        _require(alert not in active_alerts(healthy), f"告警未恢复：{alert}")
    scenarios.append(
        {
            "name": "six-required-alerts-trigger-and-recover",
            "status": "PASSED",
        }
    )

    with tempfile.TemporaryDirectory(prefix="tool-defect-p5-drill-") as directory:
        base = Path(directory)
        source = base / "source"
        manifest = base / "manifest.json"
        _build_recovery_source(source)
        created = create_recovery_point(
            source,
            manifest,
            recovery_point_id="rp-machine-drill",
            created_at=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
        )
        restored = restore_recovery_point(
            source,
            manifest,
            base / "restore",
            base / "report.json",
        )
        _require(
            verify_recovery_point(source, created)["status"] == "VERIFIED"
            and restored["status"] == "RESTORED_AND_VERIFIED",
            "联合恢复演练失败",
        )
        scenarios.append(
            {"name": "joint-recovery-and-rehash", "status": "PASSED"}
        )

        (source / "objects/raw.sha256").write_text(
            "tampered\n", encoding="utf-8"
        )
        try:
            verify_recovery_point(source, manifest)
        except RecoveryError:
            scenarios.append(
                {"name": "tampered-recovery-point", "status": "PASSED"}
            )
        else:
            raise RuntimeError("篡改恢复点没有被拒绝")

        nonempty = base / "nonempty"
        nonempty.mkdir()
        (nonempty / "owned.txt").write_text("preserve\n", encoding="utf-8")
        try:
            restore_recovery_point(
                base / "restore",
                manifest,
                nonempty,
                base / "refused-report.json",
            )
        except RecoveryError:
            scenarios.append(
                {"name": "nonempty-restore-target", "status": "PASSED"}
            )
        else:
            raise RuntimeError("非空恢复目标没有被拒绝")

    return {
        "schema_version": "tool-defect-runbook-machine-execution/v1",
        "environment": "ISOLATED_TEST",
        "executor": "deterministic-runbook-validator",
        "scenarios": scenarios,
        "status": "PASSED",
    }


def _build_recovery_source(source: Path) -> None:
    contents = {
        "database/business.dump": "business_record_count=3\n",
        "objects/raw.sha256": "raw-object-content\n",
        "models/production-model.json": '{"version":"model-v1"}\n',
        "datasets/dataset-v1.json": '{"version":"dataset-v1"}\n',
        "approvals/quality.json": '{"approved":true}\n',
        "reviews/review.json": '{"disposition":"HOLD"}\n',
    }
    for relative, content in contents.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    evidence = {
        "control_totals": {
            "business_record_count": 3,
            "object_count": 1,
            "current_model": "models/production-model.json",
            "approval_count": 1,
            "review_count": 1,
        },
        "reference_closure": sorted(contents),
    }
    (source / "recovery-evidence.json").write_text(
        json.dumps(evidence),
        encoding="utf-8",
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    print(json.dumps(run_isolated_drill(), ensure_ascii=False, indent=2))
