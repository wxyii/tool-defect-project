import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.evaluation.evaluate import evaluate
from tool_defect.training.train import train


class WorkflowTests(unittest.TestCase):
    def test_supplied_classification_model_evaluates_real_validation_samples(self):
        """Catches evaluation using the wrong artifact, labels, or input size."""
        metrics = evaluate(
            task="classification",
            config_path=PROJECT_ROOT / "configs/default.json",
            max_samples=2,
        )

        self.assertEqual(2, metrics["samples"])
        self.assertGreaterEqual(metrics["classification_accuracy"], 0.0)
        self.assertLessEqual(metrics["classification_accuracy"], 1.0)

    def test_supplied_multitask_model_evaluates_both_outputs(self):
        """Catches evaluation silently ignoring the segmentation output."""
        metrics = evaluate(
            task="multitask",
            config_path=PROJECT_ROOT / "configs/default.json",
            max_samples=2,
        )

        self.assertEqual(2, metrics["samples"])
        self.assertIn("classification_accuracy", metrics)
        self.assertIn("mean_iou", metrics)

    def test_classifier_runs_one_epoch_and_writes_new_artifacts(self):
        """Catches a nominal classifier training entry that cannot execute a batch."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = train(
                task="classification",
                config_path=PROJECT_ROOT / "configs/default.json",
                epochs=1,
                batch_size=1,
                max_samples=2,
                backbone_weights=None,
                output_dir=Path(temp_dir),
            )

            self.assertTrue((Path(temp_dir) / "model.json").is_file())
            self.assertTrue((Path(temp_dir) / "weights.h5").is_file())
            self.assertEqual(1, len(result["loss"]))

    def test_multitask_runs_one_epoch_and_writes_new_artifacts(self):
        """Catches a nominal multitask training entry that cannot execute a batch."""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = train(
                task="multitask",
                config_path=PROJECT_ROOT / "configs/default.json",
                epochs=1,
                batch_size=1,
                max_samples=2,
                backbone_weights=None,
                output_dir=Path(temp_dir),
            )

            self.assertTrue((Path(temp_dir) / "model.json").is_file())
            self.assertTrue((Path(temp_dir) / "weights.h5").is_file())
            self.assertEqual(1, len(result["loss"]))


if __name__ == "__main__":
    unittest.main()
