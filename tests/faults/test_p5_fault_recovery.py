from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from tools.operations.lifecycle_recovery import (
    RecoveryError,
    create_recovery_point,
    plan_lifecycle,
    restore_recovery_point,
    verify_recovery_point,
)
from tools.operations.alert_drill import active_alerts
from tools.operations.resilience import (
    AttemptResult,
    FaultKind,
    Outcome,
    RetryPolicy,
    execute_bounded,
    fault_outcome,
    simulate_queue,
)


class P5FaultAndRecoveryTest(unittest.TestCase):
    def test_retryable_fault_is_bounded_and_ends_in_hold(self):
        policy = RetryPolicy(
            max_attempts=4,
            initial_delay_ms=100,
            maximum_delay_ms=250,
        )
        result = execute_bounded(
            lambda _: AttemptResult(False, True, "DEPENDENCY_UNAVAILABLE"),
            policy,
        )
        self.assertEqual(Outcome.HOLD, result.status)
        self.assertEqual(4, result.attempts)
        self.assertEqual((100, 200, 250), result.delays_ms)

    def test_nonretryable_fault_stops_immediately(self):
        result = execute_bounded(
            lambda _: AttemptResult(False, False, "HASH_MISMATCH"),
            RetryPolicy(6, 100, 1_000),
        )
        self.assertEqual(Outcome.FAILED, result.status)
        self.assertEqual(1, result.attempts)
        self.assertEqual((), result.delays_ms)

    def test_every_technical_fault_fails_safe_before_and_after_recovery(self):
        for kind in FaultKind:
            with self.subTest(kind=kind):
                self.assertEqual(Outcome.HOLD, fault_outcome(kind, recovered=False))
                self.assertEqual(Outcome.HOLD, fault_outcome(kind, recovered=True))

    def test_network_outage_drains_without_loss_or_duplicate(self):
        result = simulate_queue(
            [3, 3, 3, 3, 0, 0],
            service_per_tick=2,
            outage_ticks={1, 2},
        )
        self.assertEqual(12, result.submitted)
        self.assertEqual(12, result.completed)
        self.assertEqual(0, result.lost_results)
        self.assertEqual(0, result.duplicate_results)
        self.assertEqual(0, result.final_backlog)
        self.assertGreater(result.peak_backlog, 0)

    def test_required_alerts_trigger_and_recover(self):
        healthy = {
            "production_model_ready_instances": 2,
            "dead_letter_messages": 0,
            "edge_disk_usage_ratio": 0.50,
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
        self.assertEqual(frozenset(), active_alerts(healthy))
        for alert, (metric, value) in drills.items():
            with self.subTest(alert=alert):
                fault = dict(healthy)
                fault[metric] = value
                self.assertIn(alert, active_alerts(fault))
                fault[metric] = healthy[metric]
                self.assertNotIn(alert, active_alerts(fault))
        missing = dict(healthy)
        missing.pop("database_write_probe")
        self.assertEqual(
            frozenset({"ToolDefectMonitoringBlind"}),
            active_alerts(missing),
        )

    def test_lifecycle_protects_facts_and_only_plans_cleanup(self):
        now = datetime(2026, 7, 30, tzinfo=UTC)
        old = (now - timedelta(days=120)).isoformat()
        recent = (now - timedelta(days=2)).isoformat()
        records = [
            {
                "object_key": "raw/a.png",
                "kind": "RAW_IMAGE",
                "created_at": old,
                "references": [],
            },
            {
                "object_key": "review/a.png",
                "kind": "REVIEW_MASK",
                "created_at": old,
                "references": [],
            },
            {
                "object_key": "derived/a.png",
                "kind": "DERIVED_PREVIEW",
                "created_at": old,
                "references": [],
            },
            {
                "object_key": "derived/dataset-input.png",
                "kind": "DERIVED_PREVIEW",
                "created_at": old,
                "references": [],
            },
            {
                "object_key": "datasets/v1.json",
                "kind": "DATASET",
                "created_at": old,
                "references": ["derived/dataset-input.png"],
            },
            {
                "object_key": "orphan/recent.bin",
                "kind": "TEMPORARY",
                "state": "ORPHAN",
                "created_at": recent,
                "references": [],
            },
        ]
        plan = plan_lifecycle(
            records,
            now=now,
            archive_after_days=30,
            cleanup_after_days=90,
            orphan_audit_days=14,
        )
        actions = {item["object_key"]: item for item in plan}
        self.assertEqual("RETAIN", actions["raw/a.png"]["action"])
        self.assertEqual("RETAIN", actions["review/a.png"]["action"])
        self.assertEqual(
            "CLEANUP_CANDIDATE", actions["derived/a.png"]["action"]
        )
        self.assertEqual(
            "RETAIN", actions["derived/dataset-input.png"]["action"]
        )
        self.assertEqual("RETAIN", actions["datasets/v1.json"]["action"])
        self.assertEqual("QUARANTINE", actions["orphan/recent.bin"]["action"])
        self.assertTrue(
            all(not item["destructive_action_executed"] for item in plan)
        )

    def test_joint_recovery_rehashes_and_reconciles_all_six_components(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            manifest = base / "recovery-point.json"
            destination = base / "isolated-restore"
            report = base / "drill-report.json"
            self._build_source(source)

            created = create_recovery_point(
                source,
                manifest,
                recovery_point_id="rp-20260730-001",
                created_at=datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
            )
            verified = verify_recovery_point(source, created)
            restored = restore_recovery_point(
                source, manifest, destination, report
            )

            self.assertEqual("VERIFIED", verified["status"])
            self.assertEqual("RESTORED_AND_VERIFIED", restored["status"])
            self.assertTrue(restored["isolated_destination"])
            self.assertFalse(
                restored["backup_success_treated_as_restore_success"]
            )
            self.assertEqual(6, verified["file_count"])
            self.assertEqual(
                created["control_totals"], restored["control_totals"]
            )

    def test_joint_recovery_rejects_tampered_object(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            manifest = Path(directory) / "recovery-point.json"
            self._build_source(source)
            create_recovery_point(
                source,
                manifest,
                recovery_point_id="rp-tamper-test",
                created_at=datetime(2026, 7, 30, tzinfo=UTC),
            )
            (source / "objects/raw.sha256").write_text(
                "tampered\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(RecoveryError, "哈希不一致"):
                verify_recovery_point(source, manifest)

    def test_restore_refuses_nonempty_target(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            manifest = base / "recovery-point.json"
            destination = base / "target"
            self._build_source(source)
            create_recovery_point(
                source,
                manifest,
                recovery_point_id="rp-nonempty-test",
                created_at=datetime(2026, 7, 30, tzinfo=UTC),
            )
            destination.mkdir()
            (destination / "do-not-overwrite.txt").write_text(
                "owned by user", encoding="utf-8"
            )
            with self.assertRaisesRegex(RecoveryError, "空的隔离目录"):
                restore_recovery_point(
                    source, manifest, destination, base / "report.json"
                )

    @staticmethod
    def _build_source(source: Path) -> None:
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
            json.dumps(evidence), encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main()
