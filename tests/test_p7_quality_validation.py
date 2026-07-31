"""P7-05 质量试运行严格证据测试。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.p7.common import sha256_file
from tools.p7.quality import (
    REQUIRED_EVIDENCE,
    REQUIRED_METRICS,
    REQUIRED_SIGNOFF_ROLES,
    REQUIRED_STRATA,
    validate_quality_trial_report,
)


class P7QualityValidationTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.evidence = self.root / "deploy/environments/production/evidence"
        self.evidence.mkdir(parents=True)

    def tearDown(self):
        self._temp.cleanup()

    def _evidence_file(self) -> tuple[str, str]:
        path = self.evidence / "quality-trial.log"
        path.write_text("real production quality evidence\n", encoding="utf-8")
        return str(path.relative_to(self.root)), sha256_file(path)

    def _valid_report(self) -> dict:
        log_path, log_hash = self._evidence_file()
        scope = {
            "stations": ["station-a", "station-b"],
            "shifts": ["day", "night"],
            "batches": ["batch-001", "batch-002"],
            "confidence_strata": ["LOW", "MEDIUM", "HIGH"],
            "defect_sizes": ["SMALL", "MEDIUM", "LARGE"],
            "sample_source": "REAL_PRODUCTION",
            "research_34_used_as_substitute": False,
            "sampling_method": "分层随机抽样并覆盖全量高风险区间",
            "selection_bias_assessment": "已比较抽样框与全部生产图像分布",
            "inclusion_criteria": ["真实生产批次"],
            "exclusion_criteria": [],
            "sampling_frame_coverage": 1.0,
        }
        denominators = {
            "total_images": 100,
            "inspected_images": 100,
            "defect_images": 40,
            "nondefect_images": 60,
            "ground_truth_resolved": 100,
        }
        metrics = {}
        for name, denominator_key in REQUIRED_METRICS.items():
            denominator = denominators[denominator_key]
            metrics[name] = {
                "numerator": 1,
                "denominator": denominator,
                "estimate": 1 / denominator,
                "maximum_allowed": 0.1,
                "confidence_interval_95": [0.0, 0.1],
                "status": "PASS",
            }
        stratified = {}
        for result_key, scope_key in REQUIRED_STRATA.items():
            stratified[result_key] = [
                {
                    "value": value,
                    "denominator": 10,
                    "confidence_interval_95": [0.0, 0.2],
                    "status": "PASS",
                }
                for value in scope[scope_key]
            ]
        return {
            "schema_version": "tool-defect-quality-trial/v1",
            "status": "PASS",
            "source_type": "REAL_PRODUCTION",
            "environment": "production",
            "contract_version": "v1",
            "trial_id": "quality-trial-001",
            "executor_id": "quality-executor-001",
            "started_at": "2026-07-31T01:00:00Z",
            "finished_at": "2026-07-31T05:00:00Z",
            "trial_scope": scope,
            "denominators": denominators,
            "metrics": metrics,
            "stratified_results": stratified,
            "paired_model_comparison": {
                "stable_model_version_id": "stable-model-001",
                "candidate_model_version_id": "candidate-model-002",
                "stable_package_sha256": "a" * 64,
                "candidate_package_sha256": "b" * 64,
                "paired_samples": 100,
                "method": "MCNEMAR_AND_PAIRED_BOOTSTRAP",
                "p_value": 0.04,
                "candidate_not_worse": True,
                "status": "PASS",
            },
            "evidence": {
                name: {"path": log_path, "sha256": log_hash}
                for name in REQUIRED_EVIDENCE
            },
            "model_gate": {
                "status": "PASS",
                "threshold_version": "quality-threshold-v1",
                "recommendation": "APPROVE",
            },
            "sign_offs": [
                {
                    "role": role,
                    "decision": "APPROVED",
                    "actor_id": f"{role.lower()}-approver",
                    "signed_at": "2026-07-31T06:00:00Z",
                    "reason": "真实试运行数据、统计分析与模型门槛复核完成",
                }
                for role in REQUIRED_SIGNOFF_ROLES
            ],
        }

    def _write(self, report: dict) -> Path:
        path = self.evidence / "quality-trial-report.json"
        path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
        return path

    def test_missing_report_is_blocked(self):
        result = validate_quality_trial_report(repo_root=self.root)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.errors, [])

    def test_complete_real_trial_passes(self):
        path = self._write(self._valid_report())
        result = validate_quality_trial_report(repo_root=self.root, report_path=path)
        self.assertEqual(result.status, "PASS", result.as_dict())

    def test_research_set_substitution_is_blocked(self):
        report = self._valid_report()
        report["trial_scope"]["research_34_used_as_substitute"] = True
        path = self._write(report)
        result = validate_quality_trial_report(repo_root=self.root, report_path=path)
        self.assertIn("quality_research_set_substitution_not_rejected", result.blockers)

    def test_denominator_mismatch_is_blocked(self):
        report = self._valid_report()
        report["denominators"]["inspected_images"] = 99
        path = self._write(report)
        result = validate_quality_trial_report(repo_root=self.root, report_path=path)
        self.assertIn("quality_inspected_denominator_mismatch", result.blockers)

    def test_signers_must_be_distinct(self):
        report = self._valid_report()
        for sign_off in report["sign_offs"]:
            sign_off["actor_id"] = "same-actor"
        path = self._write(report)
        result = validate_quality_trial_report(repo_root=self.root, report_path=path)
        self.assertIn("quality_signoff_actors_not_distinct", result.blockers)


if __name__ == "__main__":
    unittest.main()
