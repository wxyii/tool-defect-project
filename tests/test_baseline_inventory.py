import json
from pathlib import Path
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]

from tools.baseline.decision_checks import validate_files
from tools.baseline.hardcoded_scan import scan_hardcoded_site_parameters
from tools.baseline.inventory import build_inventory, verify_lock


class BaselineInventoryTests(unittest.TestCase):
    """验证 P0-01 资产冻结和 P0-02 现场决策安全默认。"""

    @classmethod
    def setUpClass(cls):
        cls.first = build_inventory(PROJECT_ROOT)
        cls.second = build_inventory(PROJECT_ROOT)
        cls.lock = json.loads(
            (
                PROJECT_ROOT
                / "tests/fixtures/baseline/baseline-lock.json"
            ).read_text(encoding="utf-8")
        )

    def test_full_asset_recalculation_is_deterministic_twice(self):
        self.assertEqual(self.first, self.second)
        self.assertEqual(
            "37301fdc4c5e542b1c87ef61dc76912d423fb10b1060249cc9c3d07b15c396ba",
            self.first["stable_inventory_sha256"],
        )

    def test_inventory_matches_frozen_counts_bytes_and_hashes(self):
        self.assertEqual([], verify_lock(self.first, self.lock))
        groups = self.first["asset_groups"]
        self.assertEqual(180, groups["raw_images"]["file_count"])
        self.assertEqual(4_769_700_960, groups["raw_images"]["total_bytes"])
        self.assertEqual(180, groups["raw_masks"]["file_count"])
        self.assertEqual(0, groups["labelme_annotations"]["file_count"])

    def test_dataset_facts_freeze_180_172_and_34(self):
        facts = self.first["dataset_facts"]
        self.assertEqual(180, facts["original"]["row_count"])
        self.assertEqual(
            {"train": 115, "validation": 29, "test": 36},
            facts["original"]["split_counts"],
        )
        self.assertEqual(172, facts["retraining"]["row_count"])
        self.assertEqual(
            {"train": 110, "validation": 28, "test": 34},
            facts["retraining"]["split_counts"],
        )
        self.assertEqual(34, facts["retraining_audit"]["test_samples"])
        self.assertEqual(0, facts["retraining_audit"]["cross_split_duplicate_hashes"])

    def test_historical_weights_are_evidence_only_and_not_restored(self):
        evidence = self.first["historical_weight_evidence"]
        self.assertEqual(2, len(evidence))
        expected_oids = {
            "artifacts/classification/weights.h5":
                "2887aa69abeab8cfcd1a16e167d32a2ac06dbfbcb087d2a828afb5c9eca35e76",
            "artifacts/multitask/weights.h5":
                "63de0dfbb93f3b64264e774c73109d50d110defeb9a63da411da00425890ad63",
        }
        for item in evidence:
            self.assertEqual(expected_oids[item["path"]], item["lfs_oid_sha256"])
            self.assertFalse(item["worktree_restored"])
            if item["lfs_cached_object_present"]:
                self.assertTrue(item["lfs_cached_object_hash_matches"])
                self.assertTrue(item["lfs_cached_object_size_matches"])

    def test_missing_models_and_annotations_are_explicit_blockers(self):
        blocker_codes = {item["code"] for item in self.first["blockers"]}
        self.assertIn(
            "P0-ASSET-THREE-TRAINING-MODELS-MISSING",
            blocker_codes,
        )
        self.assertIn(
            "P0-ASSET-LABELME-ANNOTATIONS-MISSING",
            blocker_codes,
        )
        self.assertIn(
            "P0-ASSET-POLAR-MODEL-INCOMPATIBLE",
            blocker_codes,
        )
        self.assertIn(
            "P0-TEST-FROZEN-BASELINE-FAILED",
            blocker_codes,
        )
        failure_register = json.loads(
            (
                PROJECT_ROOT / "Docs/baseline/failure-register.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            blocker_codes,
            {item["code"] for item in failure_register["failures"]},
        )
        for blocker in self.first["blockers"]:
            self.assertNotEqual("", blocker["safe_behavior"])
            self.assertNotEqual("", blocker["latest_gate"])
        safety_text = " ".join(
            item["safe_behavior"]
            for item in self.first["blockers"]
            if item["code"]
            in {
                "P0-ASSET-HISTORICAL-WEIGHTS-MISSING",
                "P0-ASSET-PATH-CASE-MISMATCH",
                "P0-ASSET-THREE-TRAINING-MODELS-MISSING",
                "P0-TEST-FROZEN-BASELINE-FAILED",
            }
        )
        self.assertIn("PASS", safety_text)

    def test_model_signatures_and_environment_are_recorded(self):
        model_files = {
            item["path"]: item for item in self.first["model_facts"]["files"]
        }
        classification = model_files["artifacts/classification/model.json"]
        multitask = model_files["artifacts/multitask/model.json"]
        self.assertEqual(
            [None, 299, 299, 3],
            classification["signature"]["inputs"][0]["shape"],
        )
        self.assertEqual(
            ["cla_out", "seg_out"],
            [
                output["name"]
                for output in multitask["signature"]["outputs"]
            ],
        )
        environment = self.first["environment"]
        self.assertEqual("3.11.14", environment["python_version"])
        self.assertEqual("2.13.0", environment["packages"]["tensorflow"])
        self.assertEqual(
            [
                {
                    "package": "Pillow",
                    "declared": "10.4.0",
                    "installed": "12.3.0",
                }
            ],
            environment["version_drift"],
        )

    def test_decision_registry_and_safe_configuration_validate(self):
        self.assertEqual([], validate_files(PROJECT_ROOT))
        safe_config = json.loads(
            (
                PROJECT_ROOT
                / "configs/schema/site-parameters.safe-defaults.json"
            ).read_text(encoding="utf-8")
        )
        self.assertFalse(safe_config["production_enabled"])
        self.assertFalse(
            safe_config["disposition"]["automatic_pass_enabled"]
        )
        self.assertEqual(
            "HOLD",
            safe_config["disposition"]["unknown_threshold_action"],
        )
        self.assertEqual(
            "HOLD",
            safe_config["disposition"]["technical_failure_action"],
        )
        self.assertFalse(
            safe_config["retention"]["automatic_deletion_enabled"]
        )

    def test_current_production_code_has_no_unregistered_hardcoded_site_values(self):
        self.assertEqual([], scan_hardcoded_site_parameters(PROJECT_ROOT))

    def test_hardcoded_scan_detects_a_site_threshold_literal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "apps/edge-agent/src/unsafe.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "automatic_pass_threshold = 0.95\n",
                encoding="utf-8",
            )
            findings = scan_hardcoded_site_parameters(root)
        self.assertEqual(1, len(findings))
        self.assertEqual(
            "automatic_pass_threshold",
            findings[0]["parameter"],
        )


if __name__ == "__main__":
    unittest.main()
