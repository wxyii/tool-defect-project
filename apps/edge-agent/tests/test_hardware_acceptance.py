from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


EDGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EDGE_ROOT / "src"))
sys.path.insert(0, str(EDGE_ROOT / "scripts"))

from hardware_acceptance import (
    HardwareAcceptanceRunner,
    REQUIRED_EXTERNAL_SCENARIOS,
    TestResult,
    main,
    validate_acceptance_config,
)


class HardwareAcceptanceSafetyTests(unittest.TestCase):
    def test_template_is_blocked(self) -> None:
        path = EDGE_ROOT / "scripts/hardware-acceptance-config.template.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        blockers, errors = validate_acceptance_config(config, path)
        self.assertEqual([], errors)
        self.assertIn("hardware_config_is_template", blockers)
        self.assertIn("hardware_source_not_real", blockers)

    def test_main_returns_two_and_writes_blocked_report_for_template(self) -> None:
        config = EDGE_ROOT / "scripts/hardware-acceptance-config.template.json"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.json"
            exit_code = main(["--config", str(config), "--output", str(output)])
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(2, exit_code)
        self.assertEqual("BLOCKED", report["overall_status"])
        self.assertFalse(report["production_claim_allowed"])

    def test_any_non_pass_result_denies_production_claim(self) -> None:
        runner = HardwareAcceptanceRunner(
            {"source_type": "REAL_HARDWARE", "site_id": "site-1", "run_id": "run-1"}
        )
        runner.results = [
            TestResult(test_name="camera_connectivity", status="PASS"),
            TestResult(test_name="browser_failure", status="PENDING_HARDWARE"),
        ]
        report = runner.generate_report()
        self.assertEqual("BLOCKED", report["overall_status"])
        self.assertFalse(report["production_claim_allowed"])

    def test_external_scenarios_require_real_hashed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "scenario.log"
            evidence.write_text("真实硬件场景结果", encoding="utf-8")
            digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
            config = {
                "source_type": "REAL_HARDWARE",
                "site_id": "site-1",
                "run_id": "run-1",
                "external_scenarios": [
                    {
                        "id": identifier,
                        "status": "PASS",
                        "source_type": "REAL_HARDWARE",
                        "evidence_path": evidence.name,
                        "evidence_sha256": digest,
                    }
                    for identifier in sorted(REQUIRED_EXTERNAL_SCENARIOS)
                ],
            }
            runner = HardwareAcceptanceRunner(config, config_directory=root)
            results = runner.test_external_scenarios()
        self.assertEqual(len(REQUIRED_EXTERNAL_SCENARIOS), len(results))
        self.assertTrue(all(result.status == "PASS" for result in results))


if __name__ == "__main__":
    unittest.main()
