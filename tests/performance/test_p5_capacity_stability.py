from __future__ import annotations

import unittest

from tools.operations.lifecycle_recovery import CapacityInput, calculate_capacity
from tools.operations.resilience import (
    AttemptResult,
    Outcome,
    RetryPolicy,
    execute_bounded,
    simulate_queue,
)


class P5CapacityAndStabilityTest(unittest.TestCase):
    def test_capacity_formula_is_reproducible_and_pending_signoff(self):
        input_value = CapacityInput(
            stations=4,
            captures_per_station_per_day=86_400,
            raw_bytes_per_capture=2_000_000,
            derived_bytes_per_capture=500_000,
            online_retention_days=30,
            archive_retention_days=365,
            database_bytes=500_000_000_000,
            model_and_dataset_bytes=2_000_000_000_000,
            backup_copies=2,
            headroom_ratio=0.30,
        )
        first = calculate_capacity(input_value)
        second = calculate_capacity(input_value)
        self.assertEqual(first, second)
        self.assertEqual("PENDING_SIGNOFF", first["status"])
        self.assertGreater(first["required_bytes_with_headroom"], 0)

    def test_signed_capacity_requires_explicit_input(self):
        value = CapacityInput(
            stations=1,
            captures_per_station_per_day=1,
            raw_bytes_per_capture=1,
            derived_bytes_per_capture=0,
            online_retention_days=1,
            archive_retention_days=1,
            database_bytes=0,
            model_and_dataset_bytes=0,
            backup_copies=1,
            headroom_ratio=0,
            target_signed=True,
        )
        self.assertEqual("SIGNED", calculate_capacity(value)["status"])

    def test_burst_backlog_recovers_without_loss_or_duplicate(self):
        result = simulate_queue(
            [40] * 10 + [0] * 20,
            service_per_tick=20,
            outage_ticks={3, 4, 5},
        )
        self.assertEqual(result.submitted, result.completed)
        self.assertEqual(0, result.lost_results)
        self.assertEqual(0, result.duplicate_results)
        self.assertEqual(0, result.final_backlog)
        self.assertGreater(result.peak_backlog, 100)
        self.assertGreater(result.p95_latency_ticks, 1)

    def test_long_running_retry_budget_is_constant_per_operation(self):
        policy = RetryPolicy(3, 100, 500)
        attempts = 0
        for _ in range(20_000):
            result = execute_bounded(
                lambda _: AttemptResult(False, True, "TEMPORARY"), policy
            )
            attempts += result.attempts
            self.assertEqual(Outcome.HOLD, result.status)
        self.assertEqual(60_000, attempts)
        self.assertEqual((100, 200), policy.delays())

    def test_invalid_capacity_never_silently_passes(self):
        with self.assertRaises(ValueError):
            calculate_capacity(
                CapacityInput(
                    stations=0,
                    captures_per_station_per_day=0,
                    raw_bytes_per_capture=1,
                    derived_bytes_per_capture=1,
                    online_retention_days=1,
                    archive_retention_days=1,
                    database_bytes=1,
                    model_and_dataset_bytes=1,
                    backup_copies=1,
                    headroom_ratio=0,
                )
            )


if __name__ == "__main__":
    unittest.main()
