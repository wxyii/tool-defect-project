"""P5 严重告警的确定性触发与恢复演练模型。"""

from __future__ import annotations

from typing import Mapping


REQUIRED_METRICS = frozenset(
    {
        "production_model_ready_instances",
        "dead_letter_messages",
        "edge_disk_usage_ratio",
        "database_write_probe",
        "monitoring_last_success_age_seconds",
        "hash_conflicts",
    }
)


def active_alerts(metrics: Mapping[str, float]) -> frozenset[str]:
    """按与 Prometheus 规则相同的信号判定；缺测量视为监控失明。"""

    missing = REQUIRED_METRICS - set(metrics)
    if missing:
        return frozenset({"ToolDefectMonitoringBlind"})
    values = {name: float(metrics[name]) for name in REQUIRED_METRICS}
    alerts: set[str] = set()
    if values["production_model_ready_instances"] < 1:
        alerts.add("ToolDefectProductionModelNotReady")
    if values["dead_letter_messages"] > 0:
        alerts.add("ToolDefectDeadLetterPresent")
    if values["edge_disk_usage_ratio"] >= 0.95:
        alerts.add("ToolDefectEdgeDiskCritical")
    if values["database_write_probe"] < 1:
        alerts.add("ToolDefectDatabaseUnwritable")
    if values["monitoring_last_success_age_seconds"] > 180:
        alerts.add("ToolDefectMonitoringBlind")
    if values["hash_conflicts"] > 0:
        alerts.add("ToolDefectHashConflict")
    return frozenset(alerts)
