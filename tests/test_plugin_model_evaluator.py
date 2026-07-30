import csv
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    PROJECT_ROOT / "jobs/model-evaluator/evaluate_candidates.py"
)
SPEC = importlib.util.spec_from_file_location(
    "tool_defect_model_evaluator", MODULE_PATH
)
evaluator_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(evaluator_module)


class ModelEvaluatorTests(unittest.TestCase):
    def test_documented_candidates_use_complete_registered_hashes(self):
        candidates = evaluator_module.documented_candidate_specs(
            PROJECT_ROOT
        )

        self.assertEqual(len(candidates), 3)
        for candidate in candidates:
            self.assertRegex(
                candidate.expected_model_sha256, r"^[0-9a-f]{64}$"
            )
            self.assertRegex(
                candidate.expected_weights_sha256,
                r"^[0-9a-f]{64}$",
            )
        self.assertEqual(
            candidates[2].expected_weights_sha256,
            "162526a04bc4972faff9fff13f77b37e4"
            "a3509884d33aa188303ae5b855ca545",
        )
        self.assertEqual(
            {
                candidate.fixed_test_manifest_path
                for candidate in candidates
            },
            {PROJECT_ROOT / "data/manifests/retrain.csv"},
        )

    def test_candidate_root_prefers_canonical_then_migration_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(
                evaluator_module._candidate_model_root(root),
                root / "outputs/training",
            )
            (root / "training").mkdir()
            self.assertEqual(
                evaluator_module._candidate_model_root(root),
                root / "training",
            )
            (root / "outputs/training").mkdir(parents=True)
            self.assertEqual(
                evaluator_module._candidate_model_root(root),
                root / "outputs/training",
            )

    def test_candidate_manifest_is_derived_from_frozen_34_in_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "configs"
            data_root = root / "data/candidate"
            config_dir.mkdir(parents=True)
            data_root.mkdir(parents=True)
            fixed_ids = [f"sample-{index:02d}" for index in range(34)]
            fixed_manifest = root / "data/fixed.csv"
            source_manifest = data_root / "source.csv"
            fixed_rows = [
                _manifest_row(sample_id, "test")
                for sample_id in fixed_ids
            ]
            source_rows = [
                _manifest_row(sample_id, "validation")
                for sample_id in reversed(fixed_ids)
            ]
            source_rows.extend(
                _manifest_row(f"extra-{index}", "test")
                for index in range(2)
            )
            _write_manifest(fixed_manifest, fixed_rows)
            _write_manifest(source_manifest, source_rows)
            for row in source_rows:
                for field in ("image_path", "mask_path"):
                    target = data_root / row[field]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"fixture")
            config = config_dir / "candidate.json"
            config.write_text(
                evaluator_module.json.dumps(
                    {
                        "image_size": 256,
                        "paths": {
                            "data": "data/candidate",
                            "manifest": "data/candidate/source.csv",
                            "multitask_model": "models/candidate",
                        },
                    }
                ),
                encoding="utf-8",
            )
            spec = evaluator_module.CandidateSpec(
                candidate_id="candidate",
                model_dir=root / "models/candidate",
                config_path=config,
                expected_model_sha256="0" * 64,
                expected_weights_sha256="1" * 64,
                fixed_test_manifest_path=fixed_manifest,
            )

            prepared = evaluator_module._prepare_evaluation_manifest(
                spec,
                fixed_ids,
                root / "output",
            )

            with prepared["path"].open(
                newline="", encoding="utf-8-sig"
            ) as handle:
                derived_rows = list(csv.DictReader(handle))
            self.assertEqual(
                [row["sample_id"] for row in derived_rows],
                fixed_ids,
            )
            self.assertTrue(
                all(row["split"] == "test" for row in derived_rows)
            )
            self.assertEqual(prepared["sample_count"], 34)
            self.assertRegex(prepared["manifest_sha256"], r"^[0-9a-f]{64}$")
            with source_manifest.open(
                newline="", encoding="utf-8-sig"
            ) as handle:
                unchanged_source = list(csv.DictReader(handle))
            self.assertEqual(
                [row["sample_id"] for row in unchanged_source],
                [row["sample_id"] for row in source_rows],
            )

    def test_missing_real_assets_produce_machine_readable_safe_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "controlled-output"
            fake_evaluator = mock.Mock(
                side_effect=AssertionError("不应执行评估器")
            )
            fixed = [f"sample-{index:02d}" for index in range(34)]
            mismatched = [f"other-{index:02d}" for index in range(36)]

            with mock.patch.object(
                evaluator_module,
                "_test_sample_ids",
                side_effect=[fixed, mismatched, mismatched],
            ):
                report = evaluator_module.evaluate_three_candidates(
                    evaluator_module.documented_candidate_specs(root),
                    output,
                    evaluator=fake_evaluator,
                )

            self.assertEqual(report["status"], "BLOCKED")
            self.assertFalse(report["production_claim_allowed"])
            self.assertNotIn("results", report)
            self.assertNotIn("classification_accuracy", report)
            fake_evaluator.assert_not_called()
            failure = evaluator_module.json.loads(
                (output / "failure-list.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(failure["status"], "BLOCKED")
            self.assertGreaterEqual(failure["failure_count"], 3)
            blocker_codes = {
                blocker["code"] for blocker in report["blockers"]
            }
            self.assertIn("MODEL_FILE_MISSING", blocker_codes)
            self.assertIn("TEST_SAMPLE_COUNT_MISMATCH", blocker_codes)
            self.assertIn("TEST_SAMPLE_ORDER_MISMATCH", blocker_codes)

    def test_three_candidates_are_evaluated_independently_as_test_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            specs = _candidate_specs(root)
            calls = []

            def controlled_evaluator(**kwargs):
                calls.append(Path(kwargs["model_dir"]).name)
                _write_predictions(Path(kwargs["output_dir"]))
                return {
                    "classification": {"accuracy": 1.0},
                    "segmentation": {"mean_iou": 0.5},
                    "classification_accuracy": 1.0,
                    "mean_iou": 0.5,
                    "total_standardized_loss": 0.25,
                }

            sample_ids = [f"sample-{index:02d}" for index in range(34)]
            with mock.patch.object(
                evaluator_module,
                "_test_sample_ids",
                return_value=sample_ids,
            ):
                first = evaluator_module.evaluate_three_candidates(
                    specs,
                    root / "first",
                    evaluator=controlled_evaluator,
                    bootstrap_samples=50,
                    seed=7,
                )
                second = evaluator_module.evaluate_three_candidates(
                    specs,
                    root / "second",
                    evaluator=controlled_evaluator,
                    bootstrap_samples=50,
                    seed=7,
                )

            self.assertEqual(first["status"], "COMPLETE")
            self.assertEqual(len(first["results"]), 3)
            self.assertEqual(
                calls,
                [
                    "candidate-0",
                    "candidate-1",
                    "candidate-2",
                    "candidate-0",
                    "candidate-1",
                    "candidate-2",
                ],
            )
            for left, right in zip(
                first["results"], second["results"]
            ):
                self.assertEqual(
                    left["bootstrap_95_ci"],
                    right["bootstrap_95_ci"],
                )
                self.assertEqual(
                    left["artifact"]["predictions_csv_sha256"],
                    right["artifact"]["predictions_csv_sha256"],
                )
                self.assertEqual(
                    left["candidate_status"], "TEST_CANDIDATE"
                )
                self.assertFalse(left["production_claim_allowed"])

    def test_predictions_must_match_frozen_ids_in_order_and_be_unique(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            fixed = [f"sample-{index:02d}" for index in range(34)]
            predictions = output / "predictions.csv"
            _write_predictions(output)

            evaluator_module._bootstrap_intervals(
                predictions,
                expected_sample_ids=fixed,
                samples=10,
                seed=1,
            )

            duplicate = list(fixed)
            duplicate[-1] = duplicate[0]
            _write_predictions(output, sample_ids=duplicate)
            with self.assertRaisesRegex(ValueError, "重复 sample_id"):
                evaluator_module._bootstrap_intervals(
                    predictions,
                    expected_sample_ids=fixed,
                    samples=10,
                    seed=1,
                )

            reversed_ids = list(reversed(fixed))
            _write_predictions(output, sample_ids=reversed_ids)
            with self.assertRaisesRegex(ValueError, "冻结测试清单"):
                evaluator_module._bootstrap_intervals(
                    predictions,
                    expected_sample_ids=fixed,
                    samples=10,
                    seed=1,
                )


def _candidate_specs(root):
    specs = []
    for index in range(3):
        model_dir = root / f"candidate-{index}"
        model_dir.mkdir()
        model = f'{{"candidate":{index}}}'.encode("utf-8")
        weights = f"weights-{index}".encode("utf-8")
        (model_dir / "model.json").write_bytes(model)
        (model_dir / "weights.h5").write_bytes(weights)
        config = root / f"candidate-{index}.json"
        config.write_text("{}", encoding="utf-8")
        specs.append(
            evaluator_module.CandidateSpec(
                candidate_id=f"candidate-{index}",
                model_dir=model_dir,
                config_path=config,
                expected_model_sha256=hashlib.sha256(model).hexdigest(),
                expected_weights_sha256=hashlib.sha256(
                    weights
                ).hexdigest(),
            )
        )
    return tuple(specs)


def _write_predictions(output_dir, sample_ids=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    sample_ids = sample_ids or [f"sample-{index:02d}" for index in range(34)]
    with (output_dir / "predictions.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_id",
                "true_label",
                "predicted_label",
                "defect_iou",
                "defect_dice",
            ],
        )
        writer.writeheader()
        for sample_id in sample_ids:
            writer.writerow(
                {
                    "sample_id": sample_id,
                    "true_label": "qualified",
                    "predicted_label": "qualified",
                    "defect_iou": "0.5",
                    "defect_dice": "0.6666667",
                }
            )


def _manifest_row(sample_id, split):
    safe_name = sample_id.replace("/", "_")
    return {
        "sample_id": sample_id,
        "image_path": f"images/{safe_name}.png",
        "mask_path": f"masks/{safe_name}.png",
        "annotation_path": "",
        "label": "0",
        "label_name": "qualified",
        "split": split,
    }


def _write_manifest(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_id",
                "image_path",
                "mask_path",
                "annotation_path",
                "label",
                "label_name",
                "split",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
