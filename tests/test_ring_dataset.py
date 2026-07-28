import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from tool_defect.data.ring_dataset import build_ring_dataset
from tool_defect.data.ring_geometry import Circle


def _write_png(path, image):
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError(f"unable to encode test image: {path}")
    encoded.tofile(str(path))


class RingDatasetTests(unittest.TestCase):
    def _make_source_dataset(self, root):
        rows = []
        for label_name, label, split in (
            ("qualified", 0, "validation"),
            ("unqualified", 1, "train"),
        ):
            image = np.zeros((64, 64, 3), dtype=np.uint8)
            cv2.circle(image, (32, 32), 25, (80, 80, 80), -1)
            cv2.circle(image, (32, 32), 10, (0, 0, 0), -1)
            mask = np.zeros((64, 64), dtype=np.uint8)
            if label:
                cv2.circle(image, (50, 32), 3, (255, 255, 255), -1)
                cv2.circle(mask, (50, 32), 3, 255, -1)
            name = f"{label_name}.png"
            image_relative = Path("images") / label_name / name
            mask_relative = Path("masks") / label_name / name
            _write_png(root / image_relative, image)
            _write_png(root / mask_relative, mask)
            rows.append(
                {
                    "sample_id": f"{label_name}/{name}",
                    "image_path": image_relative.as_posix(),
                    "mask_path": mask_relative.as_posix(),
                    "annotation_path": "",
                    "label": label,
                    "label_name": label_name,
                    "split": split,
                }
            )
        manifest = root / "manifests/source.csv"
        manifest.parent.mkdir(parents=True)
        with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return manifest

    @staticmethod
    def _fake_ring_result(image_path, output_size, angle_samples):
        encoded = np.fromfile(image_path, dtype=np.uint8)
        source = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        inner = np.full(angle_samples, 10.0, dtype=np.float32)
        outer = np.full(angle_samples, 25.0, dtype=np.float32)
        return SimpleNamespace(
            source=source,
            corrected=np.empty((64, 64, 3), dtype=np.uint8),
            rectification_matrix=np.array(
                [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                dtype=np.float32,
            ),
            corrected_outer_circle=Circle(32.0, 32.0, 25.0),
            inner_boundary=inner,
            outer_boundary=outer,
            polar_image=np.zeros((15, angle_samples, 3), dtype=np.uint8),
        )

    def test_adaptive_annular_dataset_preserves_splits_and_binary_masks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "adaptive"
            manifest = self._make_source_dataset(source)

            with mock.patch(
                "tool_defect.data.ring_dataset._load_ring_result",
                side_effect=lambda image_path, source_root, cache_dir,
                output_size, angle_samples: (
                    self._fake_ring_result(
                        image_path,
                        output_size,
                        angle_samples,
                    ),
                    "disabled",
                ),
            ):
                report = build_ring_dataset(
                    source,
                    manifest,
                    output,
                    "adaptive-annular",
                    cache_dir=None,
                    output_size=64,
                    angle_samples=72,
                )

            self.assertEqual("complete", report["status"])
            with (output / "manifests/dataset.csv").open(
                newline="",
                encoding="utf-8-sig",
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(
                ["validation", "train"],
                [row["split"] for row in rows],
            )
            generated_mask = cv2.imdecode(
                np.fromfile(output / rows[1]["mask_path"], dtype=np.uint8),
                cv2.IMREAD_GRAYSCALE,
            )
            self.assertEqual((64, 64), generated_mask.shape)
            self.assertEqual({0, 255}, set(np.unique(generated_mask)))
            self.assertGreater(int(np.count_nonzero(generated_mask)), 0)

    def test_boundary_normalized_image_and_mask_use_same_output_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "boundary"
            manifest = self._make_source_dataset(source)

            with mock.patch(
                "tool_defect.data.ring_dataset._load_ring_result",
                side_effect=lambda image_path, source_root, cache_dir,
                output_size, angle_samples: (
                    self._fake_ring_result(
                        image_path,
                        output_size,
                        angle_samples,
                    ),
                    "disabled",
                ),
            ):
                report = build_ring_dataset(
                    source,
                    manifest,
                    output,
                    "boundary-normalized",
                    cache_dir=None,
                    output_size=64,
                    angle_samples=72,
                    radial_samples=16,
                )

            self.assertEqual("complete", report["status"])
            with (output / "manifests/dataset.csv").open(
                newline="",
                encoding="utf-8-sig",
            ) as handle:
                rows = list(csv.DictReader(handle))
            image = cv2.imdecode(
                np.fromfile(output / rows[1]["image_path"], dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            mask = cv2.imdecode(
                np.fromfile(output / rows[1]["mask_path"], dtype=np.uint8),
                cv2.IMREAD_GRAYSCALE,
            )
            self.assertEqual((16, 72), image.shape[:2])
            self.assertEqual(image.shape[:2], mask.shape)
            self.assertGreater(int(np.count_nonzero(mask)), 0)
            payload = json.loads(
                (output / "generation_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(16, payload["radial_samples"])
            self.assertEqual([], payload["empty_positive_masks"])

    def test_empty_transformed_positive_mask_blocks_training_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            output = root / "invalid"
            manifest = self._make_source_dataset(source)

            def excluded_ring_result(
                image_path,
                source_root,
                cache_dir,
                output_size,
                angle_samples,
            ):
                result = self._fake_ring_result(
                    image_path,
                    output_size,
                    angle_samples,
                )
                result.inner_boundary[:] = 24.0
                return result, "disabled"

            with mock.patch(
                "tool_defect.data.ring_dataset._load_ring_result",
                side_effect=excluded_ring_result,
            ):
                with self.assertRaisesRegex(RuntimeError, "空的正样本掩膜"):
                    build_ring_dataset(
                        source,
                        manifest,
                        output,
                        "adaptive-annular",
                        cache_dir=None,
                        output_size=64,
                        angle_samples=72,
                    )

            self.assertFalse((output / "manifests/dataset.csv").exists())
            payload = json.loads(
                (output / "generation_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual("failed", payload["status"])
            self.assertEqual(
                ["unqualified/unqualified.png"],
                payload["empty_positive_masks"],
            )


if __name__ == "__main__":
    unittest.main()
