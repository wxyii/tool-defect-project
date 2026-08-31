"""Tests for the five-model orchestration and parent-level patch merge."""

from pathlib import Path
import csv
import json
import tempfile
import unittest
from unittest import mock

import numpy as np

from tool_defect.evaluation.multitask_suite import (
    DATASET_SPECS,
    _load_chunk_result,
    build_run_plan,
    parse_gpu_ids,
    run_suite,
)


def _write(path, content=b"x"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _prepare_plan_fixture(root):
    for spec in DATASET_SPECS:
        if spec.dataset_id == "raw":
            data_relative = Path("data")
        else:
            data_relative = Path("data") / "processed" / spec.dataset_id
        data_root = root / data_relative
        manifest_relative = data_relative / "manifests" / "dataset.csv"
        config = {
            "image_size": 256,
            "paths": {
                "data": data_relative.as_posix(),
                "manifest": manifest_relative.as_posix(),
            },
        }
        _write(root / spec.config_path, json.dumps(config))
        image_relative = Path("images/qualified/1.png")
        mask_relative = Path("masks/qualified/1.png")
        _write(data_root / image_relative)
        _write(data_root / mask_relative)
        sample_id = (
            "qualified/qualified__1__patch_00.png"
            if spec.chunked
            else "qualified/1.png"
        )
        row = {
            "sample_id": sample_id,
            "image_path": image_relative.as_posix(),
            "mask_path": mask_relative.as_posix(),
            "annotation_path": "",
            "label": "0",
            "label_name": "qualified",
            "split": "test",
        }
        manifest_path = root / manifest_relative
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        if spec.chunked:
            provenance = {
                "sample_id": sample_id,
                "parent_sample_id": "qualified/parent.png",
                "parent_image_path": "images/qualified/1.png",
                "parent_mask_path": "masks/qualified/1.png",
                "parent_label": "0",
                "parent_label_name": "qualified",
                "split": "test",
                "patch_index": "0",
                "start_angle_degrees": "0",
                "source_height": "2",
                "source_width": "4",
                "output_height": "2",
                "output_width": "2",
            }
            provenance_path = data_root / "manifests/provenance.csv"
            with provenance_path.open(
                "w", newline="", encoding="utf-8-sig"
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=list(provenance))
                writer.writeheader()
                writer.writerow(provenance)

    artifact = root / "artifacts/multitask"
    _write(artifact / "model.json", "{}")
    _write(artifact / "weights.h5")


class MultitaskSuiteTests(unittest.TestCase):
    def test_parse_gpu_ids_rejects_duplicate_assignments(self):
        self.assertEqual((0, 1, 5), parse_gpu_ids("0,1,5"))
        with self.assertRaisesRegex(ValueError, "重复"):
            parse_gpu_ids("0,1,0")

    def test_simulation_builds_plan_and_does_not_train(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _prepare_plan_fixture(root)
            output = root / "outputs/suite"
            result = run_suite(
                root,
                output_root=output,
                gpus="0,1,2,3,5",
                max_workers=2,
                simulate=True,
            )
            self.assertIsNone(result["evaluation"])
            self.assertEqual(5, len(result["plan"]["datasets"]))
            self.assertFalse(result["plan"]["datasets"][0]["train_required"])
            self.assertTrue(all(
                entry["train_required"]
                for entry in result["plan"]["datasets"][1:]
            ))
            self.assertTrue(
                result["plan"]["datasets"][3]["parent_data_root"].endswith(
                    "data\\processed\\adaptive_annular"
                )
            )
            self.assertEqual(
                [0, 1, 0, 1],
                [
                    entry["planned_gpu"]
                    for entry in result["plan"]["datasets"][1:]
                ],
            )
            self.assertTrue((output / "run_plan.json").is_file())

    @mock.patch("tool_defect.evaluation.multitask_suite._read_binary_mask")
    @mock.patch("tool_defect.evaluation.multitask_suite._read_csv")
    @mock.patch("tool_defect.evaluation.multitask_suite._load_model_predictions")
    @mock.patch("tool_defect.data.datasets.load_dataset")
    def test_boundary_patch_predictions_merge_back_to_parent(
        self,
        load_dataset,
        load_predictions,
        read_csv,
        read_mask,
    ):
        rows = [
            {"sample_id": "qualified/patch0.png"},
            {"sample_id": "qualified/patch1.png"},
        ]
        labels = np.eye(2, dtype=np.float32)[[1, 0]]
        masks = np.zeros((2, 2, 2, 2), dtype=np.float32)
        masks[..., 0] = 1.0
        images = np.zeros((2, 2, 2, 3), dtype=np.float32)
        child_segmentation = np.zeros((2, 2, 2, 2), dtype=np.float32)
        child_segmentation[..., 0] = 1.0
        child_segmentation[0, ..., 1] = [[0.1, 0.8], [0.2, 0.3]]
        child_segmentation[0, ..., 0] = 1.0 - child_segmentation[0, ..., 1]
        child_segmentation[1, ..., 1] = [[0.5, 0.4], [0.6, 0.7]]
        child_segmentation[1, ..., 0] = 1.0 - child_segmentation[1, ..., 1]
        child_classification = np.asarray(
            [[0.2, 0.8], [0.9, 0.1]], dtype=np.float32
        )
        load_dataset.return_value = (images, labels, masks, rows)
        load_predictions.return_value = (
            child_classification,
            child_segmentation,
            256,
        )
        read_csv.return_value = [
            {
                "sample_id": "qualified/patch0.png",
                "parent_sample_id": "qualified/parent.png",
                "parent_image_path": "images/qualified/parent.png",
                "parent_mask_path": "masks/qualified/parent.png",
                "parent_label": "1",
                "start_angle_degrees": "0",
                "source_height": "2",
                "source_width": "4",
                "output_height": "2",
                "output_width": "2",
            },
            {
                "sample_id": "qualified/patch1.png",
                "parent_sample_id": "qualified/parent.png",
                "parent_image_path": "images/qualified/parent.png",
                "parent_mask_path": "masks/qualified/parent.png",
                "parent_label": "1",
                "start_angle_degrees": "180",
                "source_height": "2",
                "source_width": "4",
                "output_height": "2",
                "output_width": "2",
            },
        ]
        read_mask.return_value = np.zeros((2, 4), dtype=np.uint8)
        result = _load_chunk_result(
            DATASET_SPECS[3],
            {
                "manifest": Path("manifest.csv"),
                "data_root": Path("data"),
                "artifact_dir": Path("artifact"),
                "provenance": Path("provenance.csv"),
            },
            "test",
        )
        np.testing.assert_allclose(
            result["class_probabilities"], [[0.2, 0.8]]
        )
        np.testing.assert_allclose(
            result["segmentation_probabilities"][0, ..., 1],
            [[0.1, 0.8, 0.5, 0.4], [0.2, 0.3, 0.6, 0.7]],
        )
        self.assertEqual(["qualified/parent.png"], result["parent_ids"])


if __name__ == "__main__":
    unittest.main()
