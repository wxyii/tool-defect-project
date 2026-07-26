import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.cli import main


class CliTests(unittest.TestCase):
    def test_data_check_reports_counts_without_importing_tensorflow(self):
        """Catches a data-only command being coupled to the ML runtime."""
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir)
            for relative in (
                "images/qualified",
                "images/unqualified",
                "masks/qualified",
                "masks/unqualified",
                "annotations/labelme_json",
            ):
                (data_root / relative).mkdir(parents=True, exist_ok=True)

            (data_root / "images/qualified/q.jpg").write_bytes(b"image")
            (data_root / "masks/qualified/q.jpg.png").write_bytes(b"mask")
            (data_root / "images/unqualified/u.png").write_bytes(b"image")
            (data_root / "masks/unqualified/u.png").write_bytes(b"mask")
            (data_root / "annotations/labelme_json/u.json").write_text(
                "{}", encoding="utf-8"
            )

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "data-check",
                        "--data-root",
                        str(data_root),
                        "--validation-fraction",
                        "0.2",
                    ]
                )

            self.assertEqual(0, exit_code)
            self.assertIn("qualified images: 1", output.getvalue())
            self.assertIn("unqualified images: 1", output.getvalue())
            self.assertIn("masks: 2", output.getvalue())
            self.assertIn("annotations: 1", output.getvalue())
            self.assertIn("test samples: 0", output.getvalue())

    def test_evaluate_full_metrics_writes_requested_artifacts(self):
        """Catches a full-metrics CLI that prints values but loses audit files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    [
                        "evaluate",
                        "--task",
                        "multitask",
                        "--config",
                        str(PROJECT_ROOT / "configs/default.json"),
                        "--model-dir",
                        str(PROJECT_ROOT / "artifacts/multitask"),
                        "--split",
                        "test",
                        "--max-samples",
                        "2",
                        "--output",
                        temp_dir,
                        "--full-metrics",
                    ]
                )

            self.assertEqual(0, exit_code)
            destination = Path(temp_dir)
            for name in (
                "metrics.json",
                "predictions.csv",
                "classification_confusion_matrix.csv",
                "classification_confusion_matrix.png",
                "segmentation_confusion_matrix.csv",
                "segmentation_confusion_matrix.png",
            ):
                self.assertTrue((destination / name).is_file(), name)

    def test_predict_command_runs_with_central_classification_artifact(self):
        """Catches a documented predict command that is not wired to inference."""
        image = next((PROJECT_ROOT / "data/images/qualified").iterdir())
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code = main(
                [
                    "predict",
                    "--task",
                    "classification",
                    "--input",
                    str(image),
                    "--output",
                    temp_dir,
                    "--config",
                    str(PROJECT_ROOT / "configs/default.json"),
                ]
            )

            self.assertEqual(0, exit_code)
            self.assertTrue((Path(temp_dir) / "predictions.csv").is_file())

    def test_evaluate_command_prints_machine_readable_metrics(self):
        """Catches a documented evaluation command that returns no result."""
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "evaluate",
                    "--task",
                    "classification",
                    "--config",
                    str(PROJECT_ROOT / "configs/default.json"),
                    "--max-samples",
                    "2",
                ]
            )

        self.assertEqual(0, exit_code)
        self.assertIn('"classification_accuracy"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
