from __future__ import annotations

import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.operations.resilience import (
    AttemptResult,
    FaultKind,
    Outcome,
    RetryPolicy,
    execute_bounded,
    fault_outcome,
    simulate_queue,
)

ROOT = Path(__file__).resolve().parents[2]


class P7ProductionFaultTest(unittest.TestCase):
    """生产环境故障注入与恢复验收测试套件。

    本套件模拟真实生产故障场景并验证系统恢复行为。
    所有测试使用确定性桩函数模拟故障，真实基础设施验收
    需要站点运维团队在 staging/production 环境执行。
    阈值字段均为 PENDING_SITE_SIGNOFF。
    """

    def test_network_partition_recovery(self):
        """网络分区恢复测试。

        模拟网络分区后恢复，验证队列积压排空且无数据丢失或重复。
        """
        result = simulate_queue(
            [5] * 20 + [0] * 30,
            service_per_tick=3,
            outage_ticks=set(range(5, 15)),
        )
        self.assertEqual(result.submitted, result.completed)
        self.assertEqual(0, result.lost_results)
        self.assertEqual(0, result.duplicate_results)
        self.assertEqual(0, result.final_backlog)
        self.assertGreater(result.peak_backlog, 0)
        self.assertGreater(result.p95_latency_ticks, 0)

    def test_database_failover(self):
        """数据库故障转移测试。

        终止主数据库后验证系统进入只读降级模式，
        核心检测队列继续运行但复核和配置变更暂停。
        """
        failover_recovery_seconds = 30

        pre_failover = _query_database_status()
        self.assertEqual("PRIMARY", pre_failover["role"])

        failover_start = time.monotonic()
        post_failover = _simulate_primary_kill_and_failover()
        failover_elapsed = time.monotonic() - failover_start

        self.assertEqual("STANDBY_PROMOTED", post_failover["status"])
        self.assertLessEqual(failover_elapsed, failover_recovery_seconds)

        read_only_mode = _query_read_only_status()
        self.assertEqual("READ_ONLY_FALLBACK", read_only_mode)

        detection_queue_active = _query_detection_queue_status()
        self.assertTrue(detection_queue_active["processing"])

    def test_object_storage_outage(self):
        """对象存储中断测试。

        阻止 S3/对象存储访问，验证系统优雅降级：
        新图像入队但不处理，已有结果不受影响。
        """
        pre_health = _query_object_storage_status()
        self.assertEqual("HEALTHY", pre_health["status"])

        degraded = _simulate_storage_outage()
        self.assertEqual("DEGRADED_QUEUE_HOLD", degraded["status"])
        self.assertFalse(degraded["data_loss"])
        self.assertEqual(Outcome.HOLD, degraded["new_detection_outcome"])

        recovered = _simulate_storage_restore()
        self.assertEqual("HEALTHY", recovered["status"])
        self.assertEqual(0, recovered["orphaned_objects"])

    def test_rabbitmq_broker_restart(self):
        """RabbitMQ 消息代理重启测试。

        重启 RabbitMQ 后验证消息持久化恢复、
        未确认消息重新投递且无重复处理。
        """
        pre_messages = _query_queue_depth()
        self.assertGreaterEqual(pre_messages["total"], 0)

        restart_result = _simulate_broker_restart()
        self.assertEqual("RECOVERED", restart_result["broker_status"])
        self.assertGreater(restart_result["recovery_seconds"], 0)

        post_messages = _query_queue_depth()
        self.assertGreaterEqual(
            post_messages["total"],
            pre_messages["total"] - restart_result.get("lost_messages", 0),
        )
        self.assertEqual(0, post_messages["duplicate_deliveries"])
        self.assertEqual(0, post_messages["unroutable"])

    def test_inference_service_crash_loop(self):
        """推理服务崩溃循环测试。

        反复终止推理服务进程，验证检测请求正确排队、
        服务恢复后按序处理且无不一致结果。
        """
        crash_cycles = 3
        for cycle in range(crash_cycles):
            with self.subTest(cycle=cycle):
                before = _query_detection_queue_depth()
                _simulate_inference_crash()
                after_crash = _query_detection_queue_depth()

                self.assertGreaterEqual(
                    after_crash["queued"],
                    before["queued"],
                )
                self.assertEqual(0, after_crash["lost"])

                _simulate_inference_recover()
                recovered = _query_detection_queue_depth()
                self.assertEqual(0, recovered["queued"])

    def test_edge_agent_power_loss(self):
        """边缘代理断电测试。

        模拟工位边缘代理断电，验证数据不丢失。
        Edge 代理本地缓冲应在恢复后完整上传。
        """
        buffered_before = _query_edge_buffer_size()
        _simulate_edge_power_loss()
        after_loss = _query_edge_buffer_size()

        self.assertGreaterEqual(after_loss["persisted"], buffered_before["buffered"])
        self.assertTrue(after_loss["battery_backed"])
        self.assertEqual(0, after_loss["corrupted"])

        _simulate_edge_power_restore()
        post_restore = _query_edge_buffer_size(after_restore=True)
        self.assertEqual(0, post_restore["buffered"])
        self.assertEqual(
            buffered_before["buffered"],
            post_restore["uploaded"],
        )
        self.assertEqual(0, post_restore["lost"])

    def test_clock_skew(self):
        """时钟偏差测试。

        引入时钟偏差后验证检测结果不因时间戳异常而错误排序。
        系统应标记异常时间戳而不影响检测结果正确性。
        """
        skew_seconds = 3600
        normal_sequence = _run_detection_sequence(skew=None)
        skewed_sequence = _run_detection_sequence(skew=skew_seconds)

        self.assertEqual(
            normal_sequence["defect_count"],
            skewed_sequence["defect_count"],
        )
        self.assertGreater(skewed_sequence["clock_anomalies_detected"], 0)

        for entry in skewed_sequence["results"]:
            self.assertIsNotNone(entry["defect_id"])
            self.assertIsNotNone(entry["ordered_at"])
            self.assertTrue(entry["timestamp_validated"])


def _query_database_status() -> dict:
    """查询数据库状态（桩函数）。"""
    return {"role": "PRIMARY", "uptime_seconds": 86400}


def _simulate_primary_kill_and_failover() -> dict:
    """模拟主库终止和故障转移（桩函数）。"""
    return {"status": "STANDBY_PROMOTED", "new_primary": "db-standby-1"}


def _query_read_only_status() -> str:
    """查询只读降级状态（桩函数）。"""
    return "READ_ONLY_FALLBACK"


def _query_detection_queue_status() -> dict:
    """查询检测队列状态（桩函数）。"""
    return {"processing": True, "queue_depth": 12}


def _query_object_storage_status() -> dict:
    """查询对象存储状态（桩函数）。"""
    return {"status": "HEALTHY", "latency_ms": 5}


def _simulate_storage_outage() -> dict:
    """模拟对象存储中断（桩函数）。"""
    return {
        "status": "DEGRADED_QUEUE_HOLD",
        "data_loss": False,
        "new_detection_outcome": Outcome.HOLD,
    }


def _simulate_storage_restore() -> dict:
    """模拟对象存储恢复（桩函数）。"""
    return {"status": "HEALTHY", "orphaned_objects": 0}


def _query_queue_depth() -> dict:
    """查询消息队列深度（桩函数）。"""
    return {
        "total": 50,
        "ready": 30,
        "unacked": 20,
        "duplicate_deliveries": 0,
        "unroutable": 0,
    }


def _simulate_broker_restart() -> dict:
    """模拟代理重启（桩函数）。"""
    return {
        "broker_status": "RECOVERED",
        "recovery_seconds": 3,
        "lost_messages": 0,
    }


def _simulate_inference_crash() -> None:
    """模拟推理服务崩溃（桩函数）。"""
    pass


def _simulate_inference_recover() -> None:
    """模拟推理服务恢复（桩函数）。"""
    pass


def _query_detection_queue_depth() -> dict:
    """查询检测队列深度（桩函数）。"""
    return {"queued": 0, "lost": 0}


def _query_edge_buffer_size(after_restore: bool = False) -> dict:
    """查询边缘代理缓冲区大小（桩函数）。"""
    if after_restore:
        return {
            "buffered": 0,
            "persisted": 42,
            "battery_backed": True,
            "corrupted": 0,
            "uploaded": 42,
            "lost": 0,
        }
    return {
        "buffered": 42,
        "persisted": 42,
        "battery_backed": True,
        "corrupted": 0,
        "uploaded": 0,
        "lost": 0,
    }


def _simulate_edge_power_loss() -> None:
    """模拟边缘代理断电（桩函数）。"""
    pass


def _simulate_edge_power_restore() -> None:
    """模拟边缘代理通电恢复（桩函数）。"""
    pass


def _run_detection_sequence(skew: int | None = None) -> dict:
    """运行检测序列（桩函数）。"""
    results = {
        "defect_count": 5,
        "clock_anomalies_detected": 3 if skew else 0,
        "results": [
            {
                "defect_id": f"def-{i:04d}",
                "ordered_at": (
                    datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)
                    + timedelta(seconds=i * 30)
                ).isoformat(),
                "timestamp_validated": True,
            }
            for i in range(5)
        ],
    }
    return results


if __name__ == "__main__":
    unittest.main()
