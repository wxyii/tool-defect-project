"""性能测试共享工具集。

本项目使用 unittest discover 运行测试，因此本模块提供可导入的
常量、工厂与辅助函数，而不是 pytest 风格的 fixture 定义。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PENDING_SITE_SIGNOFF = "PENDING_SITE_SIGNOFF"

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SITE_CONFIG_PATH = ROOT / "config" / "site" / "production-thresholds.json"

_report_sections: list[dict[str, Any]] = []


@dataclass
class LatencyResult:
    operation: str
    sample_count: int
    p50: float
    p95: float
    p99: float
    p999: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    mean_ms: float = 0.0
    stddev_ms: float = 0.0
    warmup_discarded: int = 0


@dataclass
class ThroughputResult:
    operation: str
    duration_seconds: float
    concurrency: int
    completed: int
    failures: int
    throughput_per_second: float
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0


@dataclass
class StratumSample:
    stratum: str
    expected_minimum: int
    actual_count: int
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0


def load_site_threshold(key: str, default: Any) -> Any:
    """从站点配置文件加载阈值。

    如果配置文件存在且包含对应键，返回配置值；
    否则返回默认值（通常为 PENDING_SITE_SIGNOFF）。
    """
    try:
        config = json.loads(DEFAULT_SITE_CONFIG_PATH.read_text(encoding="utf-8"))
        return config.get(key, default)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def measure_latency(
    operation: str,
    sample_count: int = 200,
    warmup_attempts: int = 5,
) -> dict:
    """测量操作延迟分布。

    返回 P50/P95/P99 百分位延迟及采样信息。
    在生产环境中应连接真实服务端点；当前为桩实现。
    """
    for _ in range(warmup_attempts):
        time.sleep(0.001)

    base_latency = 0.050
    samples = [base_latency + (i % 20) * 0.005 for i in range(sample_count)]
    samples.sort()

    def percentile(data: list[float], pct: float) -> float:
        index = int(len(data) * pct / 100)
        return data[min(index, len(data) - 1)]

    return {
        "operation": operation,
        "sample_count": sample_count,
        "p50": round(percentile(samples, 50), 3),
        "p95": round(percentile(samples, 95), 3),
        "p99": round(percentile(samples, 99), 3),
        "p999": round(percentile(samples, 99.9), 3),
        "min_ms": round(samples[0], 3),
        "max_ms": round(samples[-1], 3),
        "mean_ms": round(sum(samples) / len(samples), 3),
        "warmup_discarded": warmup_attempts,
    }


def measure_throughput(
    operation: str,
    duration_seconds: int = 60,
    warmup_seconds: int = 15,
    concurrent_count: int = 1,
    batch_count: int = 1,
) -> dict:
    """测量操作吞吐量。

    在指定时长内持续发送请求并统计吞吐量。
    在生产环境中应连接真实服务端点；当前为桩实现。
    """
    if batch_count > 1:
        completed = concurrent_count * batch_count
    else:
        completed = duration_seconds * 100 * concurrent_count
    return {
        "operation": operation,
        "duration_seconds": duration_seconds,
        "concurrency": concurrent_count,
        "completed": completed,
        "failures": 0,
        "throughput_per_second": float(completed) / max(duration_seconds, 1),
        "batch_count": batch_count,
        "p50_latency_ms": 12.5,
        "p95_latency_ms": 35.0,
        "p99_latency_ms": 80.0,
    }


def report_section(title: str, metrics: dict[str, Any]) -> None:
    """记录报告段落到全局报告列表。

    用于在测试完成后生成聚合验收报告。
    """
    _report_sections.append(
        {
            "title": title,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "metrics": metrics,
        }
    )


def generate_report() -> str:
    """生成聚合性能报告 JSON 字符串。

    收集所有 report_section 调用中记录的数据。
    """
    report = {
        "report_type": "P7-non-functional-acceptance",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": PENDING_SITE_SIGNOFF,
        "sections": _report_sections,
    }
    return json.dumps(report, ensure_ascii=False, indent=2)


def clear_report() -> None:
    """清空全局报告累积数据。"""
    _report_sections.clear()


def bootstrap_confidence_interval(
    values: list[float],
    n_bootstrap: int = 10000,
    confidence: float = 0.95,
) -> tuple[float, float, float]:
    """Bootstrap 置信区间计算。

    返回 (lower, mean, upper) 三元组。
    """
    import random

    if not values:
        return (0.0, 0.0, 0.0)

    n = len(values)
    means = []
    rng = random.Random(42)
    for _ in range(n_bootstrap):
        sample = [values[rng.randint(0, n - 1)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()

    alpha = (1 - confidence) / 2
    lower_idx = int(n_bootstrap * alpha)
    upper_idx = int(n_bootstrap * (1 - alpha))

    return (
        round(means[lower_idx], 4),
        round(sum(values) / n, 4),
        round(means[upper_idx], 4),
    )
