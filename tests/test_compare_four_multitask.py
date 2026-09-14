import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from tool_defect.evaluation.compare_four_multitask import (
    compare_four_multitask,
)


def _parent_result(parent_ids):
    count = len(parent_ids)
    masks = np.zeros((count, 4, 4, 2), dtype=np.float32)
    masks[..., 0] = 1.0
    probabilities = np.zeros_like(masks)
    probabilities[..., 0] = 1.0
    return {
        "parent_ids": list(parent_ids),
        "true_labels": np.zeros(count, dtype=np.int32),
        "class_probabilities": np.tile([[0.8, 0.2]], (count, 1)),
        "segmentation_probabilities": probabilities,
        "masks": masks,
        "parent_images": [Path(f"{item}.png") for item in parent_ids],
        "input_size": 4,
        # This deliberately differs from the parent count. It must remain
        # auxiliary and must never become the main sample count.
        "patch_metrics": {"samples": count * 8},
    }


class CompareFourMultitaskTests(unittest.TestCase):
    @mock.patch("tool_defect.evaluation.compare_four_multitask._write_json")
    @mock.patch(
        "tool_defect.evaluation.compare_four_multitask._write_four_group_report"
    )
    @mock.patch(
        "tool_defect.evaluation.compare_four_multitask._write_model_outputs"
    )
    @mock.patch(
        "tool_defect.evaluation.compare_four_multitask._load_dataset_result"
    )
    @mock.patch(
        "tool_defect.evaluation.compare_four_multitask._load_spec_paths"
    )
    @mock.patch(
        "tool_defect.evaluation.compare_four_multitask._validate_data_inputs",
        return_value=[],
    )
    @mock.patch(
        "tool_defect.evaluation.compare_four_multitask.artifact_status",
        return_value={"complete": True, "missing": [], "directory": "artifact"},
    )
    def test_four_groups_report_parent_count_for_chunked_models(
        self,
        _status,
        _validate,
        load_paths,
        load_result,
        write_outputs,
        write_report,
        write_json,
    ):
        parent_ids = ["qualified/1.png", "unqualified/2.png"]
        load_paths.return_value = {
            "artifact_dir": Path("artifact"),
            "config": Path("config.json"),
        }
        load_result.side_effect = lambda spec, paths, split: _parent_result(
            list(reversed(parent_ids))
            if spec.dataset_id.endswith("_b")
            else parent_ids
        )
        write_outputs.side_effect = lambda spec, result, output, split, threshold: {
            "dataset_id": spec.dataset_id,
            "dataset_name": spec.name,
            "evaluation_level": "parent",
            "samples": len(result["parent_ids"]),
            "classification_accuracy": 0.5,
            "classification": {"unqualified": {"precision": 0.0, "recall": 0.0, "f1": 0.0}},
            "segmentation": {"defect": {"iou": 0.0, "dice": 0.0, "precision": 0.0, "recall": 0.0}},
            "mean_iou": 0.0,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            result = compare_four_multitask(
                project_root=Path(temp_dir),
                whole_config=Path("whole.json"),
                whole_a=Path("whole_a"),
                whole_b=Path("whole_b"),
                patch_config=Path("patch.json"),
                patch_a=Path("patch_a"),
                patch_b=Path("patch_b"),
                output_dir=Path(temp_dir) / "output",
                patch_parent_data=Path("parent_data"),
            )

        self.assertEqual(2, result["samples"])
        self.assertEqual(4, len(result["groups"]))
        self.assertTrue(all(item["evaluation_level"] == "parent" for item in result["groups"]))
        self.assertEqual(16, result["groups"][2]["patch_level_auxiliary_samples"])
        self.assertEqual(16, result["groups"][3]["patch_level_auxiliary_samples"])
        write_report.assert_called_once()
        write_json.assert_called_once()


if __name__ == "__main__":
    unittest.main()
