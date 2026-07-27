import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import tensorflow as tf
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tool_defect.evaluation.compare_multitask import compare_multitask_models


def _model(good):
    inputs = tf.keras.Input((8, 8, 3))
    pooled = tf.keras.layers.GlobalAveragePooling2D()(inputs)
    classification = tf.keras.layers.Dense(
        2, activation="softmax", name="cla_out"
    )(pooled)
    segmentation = tf.keras.layers.Conv2D(
        2, 1, activation="softmax", name="seg_out"
    )(inputs)
    model = tf.keras.Model(inputs, [classification, segmentation])
    if good:
        model.get_layer("cla_out").set_weights(
            [
                np.asarray([[-10, 10], [-10, 10], [-10, 10]], np.float32),
                np.asarray([1, -1], np.float32),
            ]
        )
        model.get_layer("seg_out").set_weights(
            [
                np.asarray([[[[-3, 3], [-3, 3], [-3, 3]]]], np.float32),
                np.asarray([2, -2], np.float32),
            ]
        )
    else:
        model.get_layer("cla_out").set_weights(
            [
                np.zeros((3, 2), np.float32),
                np.asarray([3, -3], np.float32),
            ]
        )
        model.get_layer("seg_out").set_weights(
            [
                np.zeros((1, 1, 3, 2), np.float32),
                np.asarray([3, -3], np.float32),
            ]
        )
    return model


def _write_fixture(root):
    data_root = root / "data"
    rows = []
    for index, (label_name, label) in enumerate(
        [
            ("qualified", 0),
            ("unqualified", 1),
            ("qualified", 0),
            ("unqualified", 1),
        ]
    ):
        image_rel = Path("images") / label_name / f"{index}.png"
        mask_rel = Path("masks") / label_name / f"{index}.png"
        image_path = data_root / image_rel
        mask_path = data_root / mask_rel
        image_path.parent.mkdir(parents=True, exist_ok=True)
        mask_path.parent.mkdir(parents=True, exist_ok=True)
        mask = np.zeros((8, 8), dtype=np.uint8)
        if label:
            mask[2:5, 3:6] = 255
        Image.fromarray(np.repeat(mask[..., None], 3, axis=-1)).save(image_path)
        Image.fromarray(mask).save(mask_path)
        rows.append(
            {
                "sample_id": f"{label_name}/{index}.png",
                "image_path": image_rel.as_posix(),
                "mask_path": mask_rel.as_posix(),
                "annotation_path": "",
                "label": str(label),
                "label_name": label_name,
                "split": "test",
            }
        )
    manifest = data_root / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    for name, good in (("baseline", False), ("candidate", True)):
        directory = root / name
        directory.mkdir()
        model = _model(good)
        (directory / "model.json").write_text(model.to_json(), encoding="utf-8")
        model.save_weights(directory / "weights.h5")

    config_dir = root / "configs"
    config_dir.mkdir()
    config_path = config_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "image_size": 8,
                "paths": {
                    "data": "data",
                    "manifest": "data/manifest.csv",
                    "multitask_model": "baseline",
                    "outputs": "outputs",
                },
            }
        ),
        encoding="utf-8",
    )
    return config_path, manifest, rows


class CompareMultitaskTests(unittest.TestCase):
    def test_comparison_uses_same_order_and_reports_paired_improvement(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config, manifest, source_rows = _write_fixture(root)
            output = root / "comparison"
            result = compare_multitask_models(
                config_path=config,
                manifest_path=manifest,
                baseline_model_dir=root / "baseline",
                candidate_model_dir=root / "candidate",
                output_dir=output,
                bootstrap_samples=30,
                seed=1,
            )
            repeated = compare_multitask_models(
                config_path=config,
                manifest_path=manifest,
                baseline_model_dir=root / "baseline",
                candidate_model_dir=root / "candidate",
                output_dir=root / "comparison_repeated",
                bootstrap_samples=30,
                seed=1,
            )
            with (output / "predictions.csv").open(
                newline="", encoding="utf-8-sig"
            ) as handle:
                predictions = list(csv.DictReader(handle))

            self.assertEqual(
                [row["sample_id"] for row in source_rows],
                [row["sample_id"] for row in predictions],
            )
            self.assertGreater(result["delta"]["classification_accuracy"], 0)
            self.assertGreater(result["delta"]["defect_iou"], 0)
            self.assertEqual(
                result["bootstrap_95_ci"], repeated["bootstrap_95_ci"]
            )
            for name in (
                "comparison.json",
                "COMPARISON_REPORT.md",
                "predictions.csv",
                "baseline_classification_confusion_matrix.csv",
                "candidate_classification_confusion_matrix.csv",
                "baseline_segmentation_confusion_matrix.csv",
                "candidate_segmentation_confusion_matrix.csv",
            ):
                self.assertTrue((output / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
