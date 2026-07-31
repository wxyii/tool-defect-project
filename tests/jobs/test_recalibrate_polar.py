"""P6-04 极坐标模型重标定单元测试。"""

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

MODULE_PATH = PROJECT_ROOT / "jobs/model-evaluator/recalibrate_polar.py"
SPEC = importlib.util.spec_from_file_location(
    "tool_defect_polar_recalibrate", MODULE_PATH
)
recalibrate_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(recalibrate_module)

from tool_defect.detection.polar_anomaly import (
    FEATURE_NAMES,
    MODEL_VERSION,
    PolarAnomalyModel,
)


def _legacy_model_payload(version=1):
    return {
        "version": version,
        "feature_centers": [1.0, 2.0, 3.0],
        "feature_scales": [0.5, 0.6, 0.7],
        "threshold": 6.0,
        "output_size": 512,
        "angle_samples": 1440,
        "minimum_periods": 8,
        "maximum_periods": 40,
        "calibration_images": 0,
        "failed_images": 0,
        "feature_names": list(FEATURE_NAMES),
    }


def _default_calibration_report():
    return {
        "model_path": "",
        "input_images": 34,
        "calibration_images": 34,
        "failed_images": 0,
        "cache_hits": 34,
        "cache_rebuilt": 0,
        "period_counts": {"24": 34},
        "threshold": 6.0,
        "feature_centers": {"texture": 1.0, "gradient": 2.0, "boundary": 3.0},
        "feature_scales": {"texture": 0.5, "gradient": 0.6, "boundary": 0.7},
        "robust_feature_scales": {"texture": 0.5, "gradient": 0.6, "boundary": 0.7},
        "tail_scale_factors": {"texture": 1.0, "gradient": 1.0, "boundary": 1.0},
        "failures": [],
    }


def _default_detection_report():
    return {
        "input_images": 34,
        "successful_images": 34,
        "failed_images": 0,
        "images_with_regions": 5,
        "threshold": 6.0,
        "score_distribution": {
            "minimum": 0.1,
            "median": 1.2,
            "maximum": 15.0,
            "p90": 4.0,
            "p95": 6.5,
        },
    }


def _make_v2_model():
    return PolarAnomalyModel(
        version=MODEL_VERSION,
        feature_centers=(1.0, 2.0, 3.0),
        feature_scales=(0.5, 0.6, 0.7),
        threshold=6.0,
        output_size=512,
        angle_samples=1440,
        minimum_periods=8,
        maximum_periods=40,
        calibration_images=34,
    )


class VersionDetectionTests(unittest.TestCase):
    """版本检测：旧版本 1 模型必须被拒绝。"""

    def test_legacy_version_1_model_is_rejected_with_blocker_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_path = root / "polar_anomaly_v1.json"
            payload = _legacy_model_payload(version=1)
            legacy_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            audit = recalibrate_module._audit_legacy_model(legacy_path)

            self.assertEqual(audit["observed_version"], 1)
            self.assertEqual(audit["status"], "REJECTED")
            self.assertGreater(len(audit["blockers"]), 0)
            blocker_codes = {b["code"] for b in audit["blockers"]}
            self.assertIn("LEGACY_VERSION_REJECTED", blocker_codes)
            self.assertEqual(audit["expected_version"], 1)
            self.assertEqual(audit["required_version"], MODEL_VERSION)

    def test_unrecognized_version_produces_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_path = root / "polar_anomaly_v99.json"
            payload = _legacy_model_payload(version=99)
            legacy_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            audit = recalibrate_module._audit_legacy_model(legacy_path)

            self.assertEqual(audit["observed_version"], 99)
            self.assertEqual(audit["status"], "REJECTED")
            blocker_codes = {b["code"] for b in audit["blockers"]}
            self.assertIn("UNRECOGNIZED_VERSION", blocker_codes)

    def test_current_version_in_legacy_path_raises_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = PolarAnomalyModel(
                version=MODEL_VERSION,
                feature_centers=(1.0, 2.0, 3.0),
                feature_scales=(0.5, 0.6, 0.7),
                threshold=6.0,
                calibration_images=34,
            )
            model_path = model.save(root / "model")

            with self.assertRaises(ValueError):
                recalibrate_module._audit_legacy_model(model_path)

    def test_polar_model_load_rejects_version_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_path = root / "polar_anomaly_v1.json"
            payload = _legacy_model_payload(version=1)
            legacy_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as ctx:
                PolarAnomalyModel.load(legacy_path)
            self.assertIn(
                str(payload["version"]), str(ctx.exception)
            )

    def test_model_version_constant_is_two(self):
        self.assertEqual(MODEL_VERSION, 2)


class _RecalibrationMixin(unittest.TestCase):
    """为重标定流程测试创建合成图像输入目录。"""

    @staticmethod
    def _write_polar_input_directory(root: Path, count: int):
        import cv2

        images_dir = root / "images"
        images_dir.mkdir(parents=True)
        for index in range(count):
            image_path = images_dir / f"blade_{index:04d}.png"
            source = np.full((160, 160, 3), 100, dtype=np.uint8)
            encoded = cv2.imencode(".png", source)[1]
            encoded.tofile(str(image_path))
        return images_dir


class RecalibrationProcessTests(_RecalibrationMixin):
    """重标定流程验证：使用模拟标定器和检测器。"""

    def test_recalibration_blocks_on_sample_count_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self._write_polar_input_directory(root, 10)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"

            spec = recalibrate_module.RecalibrationSpec(
                spec_id="polar-v2-test",
                input_dir=input_dir,
                cache_dir=cache_dir,
                output_dir=output_dir,
            )

            report = recalibrate_module.recalibrate_polar_model(spec)

            self.assertEqual(report["status"], "BLOCKED")
            blocker_codes = {b["code"] for b in report["blockers"]}
            self.assertIn("TEST_SAMPLE_COUNT_MISMATCH", blocker_codes)
            self.assertFalse(report["production_claim_allowed"])

    def test_recalibration_completes_with_34_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self._write_polar_input_directory(root, 34)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"

            model = _make_v2_model()
            calibration_report = _default_calibration_report()

            with mock.patch.object(
                recalibrate_module,
                "fit_unlabeled_model",
                return_value=(model, calibration_report),
            ), mock.patch.object(
                recalibrate_module,
                "run_detection",
                return_value=_default_detection_report(),
            ):
                spec = recalibrate_module.RecalibrationSpec(
                    spec_id="polar-v2-test",
                    input_dir=input_dir,
                    cache_dir=cache_dir,
                    output_dir=output_dir,
                )

                report = recalibrate_module.recalibrate_polar_model(spec)

            self.assertEqual(report["status"], "COMPLETE")
            self.assertFalse(report["production_claim_allowed"])
            self.assertEqual(report["model_version_target"], MODEL_VERSION)
            self.assertIn("model_metadata", report)
            self.assertEqual(report["model_metadata"]["version"], MODEL_VERSION)
            self.assertIn("feature_centers", report["model_metadata"])
            self.assertIn("feature_scales", report["model_metadata"])
            self.assertEqual(
                len(report["model_metadata"]["feature_centers"]),
                len(FEATURE_NAMES),
            )
            self.assertEqual(
                len(report["model_metadata"]["feature_scales"]),
                len(FEATURE_NAMES),
            )
            self.assertIn("recalibration_metrics", report)
            self.assertIn("runtime", report)
            self.assertEqual(
                report["recalibration_metrics"]["calibration"]["calibration_images"],
                34,
            )

    def test_legacy_model_in_spec_adds_audit_and_proceeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self._write_polar_input_directory(root, 34)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"

            legacy_path = root / "polar_anomaly_v1.json"
            payload = _legacy_model_payload(version=1)
            legacy_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            model = _make_v2_model()
            calibration_report = _default_calibration_report()

            with mock.patch.object(
                recalibrate_module,
                "fit_unlabeled_model",
                return_value=(model, calibration_report),
            ), mock.patch.object(
                recalibrate_module,
                "run_detection",
                return_value=_default_detection_report(),
            ):
                spec = recalibrate_module.RecalibrationSpec(
                    spec_id="polar-v2-test",
                    input_dir=input_dir,
                    cache_dir=cache_dir,
                    output_dir=output_dir,
                    legacy_model_path=legacy_path,
                )

                report = recalibrate_module.recalibrate_polar_model(spec)

            self.assertEqual(report["status"], "COMPLETE")
            self.assertIn("legacy_model", report["provenance"])
            self.assertEqual(
                report["provenance"]["legacy_model"]["status"], "REJECTED"
            )
            self.assertFalse(report["production_claim_allowed"])

    def test_calibration_failure_produces_blocked_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self._write_polar_input_directory(root, 34)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"

            with mock.patch.object(
                recalibrate_module,
                "fit_unlabeled_model",
                side_effect=RuntimeError("所有图像均无法用于标定"),
            ):
                spec = recalibrate_module.RecalibrationSpec(
                    spec_id="polar-v2-test",
                    input_dir=input_dir,
                    cache_dir=cache_dir,
                    output_dir=output_dir,
                )

                report = recalibrate_module.recalibrate_polar_model(spec)

            self.assertEqual(report["status"], "BLOCKED")
            blocker_codes = {b["code"] for b in report["blockers"]}
            self.assertIn("CALIBRATION_FAILED", blocker_codes)
            self.assertFalse(report["production_claim_allowed"])

    def test_version_mismatch_after_calibration_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self._write_polar_input_directory(root, 34)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"

            wrong_model = PolarAnomalyModel(
                version=99,
                feature_centers=(1.0, 2.0, 3.0),
                feature_scales=(0.5, 0.6, 0.7),
                threshold=6.0,
                calibration_images=34,
            )

            with mock.patch.object(
                recalibrate_module,
                "fit_unlabeled_model",
                return_value=(wrong_model, _default_calibration_report()),
            ):
                spec = recalibrate_module.RecalibrationSpec(
                    spec_id="polar-v2-test",
                    input_dir=input_dir,
                    cache_dir=cache_dir,
                    output_dir=output_dir,
                )

                report = recalibrate_module.recalibrate_polar_model(spec)

            self.assertEqual(report["status"], "BLOCKED")
            blocker_codes = {b["code"] for b in report["blockers"]}
            self.assertIn("VERSION_MISMATCH_AFTER_CALIBRATION", blocker_codes)


class ReportIntegrityTests(_RecalibrationMixin):
    """报告完整性校验。"""

    def _run_successful_recalibration(self, output_dir, input_dir, cache_dir):
        model = _make_v2_model()

        with mock.patch.object(
            recalibrate_module,
            "fit_unlabeled_model",
            return_value=(model, _default_calibration_report()),
        ), mock.patch.object(
            recalibrate_module,
            "run_detection",
            return_value=_default_detection_report(),
        ):
            spec = recalibrate_module.RecalibrationSpec(
                spec_id="polar-v2-test",
                input_dir=input_dir,
                cache_dir=cache_dir,
                output_dir=output_dir,
            )

            return recalibrate_module.recalibrate_polar_model(spec)

    def test_report_json_exists_and_has_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self._write_polar_input_directory(root, 34)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"

            self._run_successful_recalibration(output_dir, input_dir, cache_dir)

            report_path = output_dir / "report.json"
            self.assertTrue(report_path.is_file())

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "COMPLETE")
            self.assertIn("schema_version", report)
            self.assertIn("production_claim_allowed", report)
            self.assertIn("provenance", report)
            self.assertIn("model_metadata", report)
            self.assertIn("recalibration_metrics", report)
            self.assertIn("runtime", report)
            self.assertIn("fixed_test_samples_required", report)
            self.assertEqual(report["fixed_test_samples_required"], 34)

    def test_provenance_json_exists_and_is_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self._write_polar_input_directory(root, 34)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"

            self._run_successful_recalibration(output_dir, input_dir, cache_dir)

            provenance_path = output_dir / "provenance.json"
            self.assertTrue(provenance_path.is_file())

            provenance = json.loads(
                provenance_path.read_text(encoding="utf-8")
            )
            self.assertIn("schema_version", provenance)
            self.assertIn("recalibration_type", provenance)
            self.assertIn("spec_id", provenance)
            self.assertIn("target_model_version", provenance)
            self.assertIn("report_sha256", provenance)
            self.assertIn("generated_at", provenance)
            self.assertFalse(provenance["production_claim_allowed"])
            self.assertIn("input_images", provenance)
            self.assertIn("test_set", provenance)

    def test_failure_list_written_even_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self._write_polar_input_directory(root, 34)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"

            self._run_successful_recalibration(output_dir, input_dir, cache_dir)

            failure_path = output_dir / "failure-list.json"
            self.assertTrue(failure_path.is_file())

            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            self.assertEqual(failure["status"], "EMPTY")
            self.assertEqual(failure["failure_count"], 0)
            self.assertFalse(failure["production_claim_allowed"])

    def test_small_input_produces_blocked_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self._write_polar_input_directory(root, 5)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"

            spec = recalibrate_module.RecalibrationSpec(
                spec_id="polar-v2-test",
                input_dir=input_dir,
                cache_dir=cache_dir,
                output_dir=output_dir,
            )

            recalibrate_module.recalibrate_polar_model(spec)

            report_path = output_dir / "report.json"
            self.assertTrue(report_path.is_file())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "BLOCKED")

            failure_path = output_dir / "failure-list.json"
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            self.assertEqual(failure["status"], "BLOCKED")
            self.assertGreater(failure["failure_count"], 0)

    def test_test_data_directory_contains_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self._write_polar_input_directory(root, 34)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"

            self._run_successful_recalibration(output_dir, input_dir, cache_dir)

            test_data_dir = output_dir / "test-data"
            self.assertTrue(test_data_dir.is_dir())

            snapshot = test_data_dir / "model-snapshot.json"
            self.assertTrue(snapshot.is_file())
            data = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertIn("model_version", data)
            self.assertIn("threshold", data)
            self.assertIn("feature_centers", data)
            self.assertIn("feature_scales", data)
            self.assertFalse(data["production_claim_allowed"])

            test_ids = test_data_dir / "test-set-ids.json"
            self.assertTrue(test_ids.is_file())
            ids_data = json.loads(test_ids.read_text(encoding="utf-8"))
            self.assertEqual(ids_data["sample_count"], 34)
            self.assertEqual(ids_data["fixed_count"], 34)

    def test_production_claim_never_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self._write_polar_input_directory(root, 34)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"

            report = self._run_successful_recalibration(
                output_dir, input_dir, cache_dir
            )
            self.assertFalse(report["production_claim_allowed"])

            for file_name in (
                "report.json",
                "provenance.json",
                "failure-list.json",
            ):
                payload = json.loads(
                    (output_dir / file_name).read_text(encoding="utf-8")
                )
                self.assertFalse(payload["production_claim_allowed"])

    def test_blocked_report_writes_reports_with_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = self._write_polar_input_directory(root, 34)
            cache_dir = root / "cache"
            cache_dir.mkdir()
            output_dir = root / "output"

            model = _make_v2_model()

            with mock.patch.object(
                recalibrate_module,
                "fit_unlabeled_model",
                return_value=(model, _default_calibration_report()),
            ), mock.patch.object(
                recalibrate_module,
                "run_detection",
                side_effect=RuntimeError("检测阶段失败"),
            ):
                spec = recalibrate_module.RecalibrationSpec(
                    spec_id="polar-v2-test",
                    input_dir=input_dir,
                    cache_dir=cache_dir,
                    output_dir=output_dir,
                )

                report = recalibrate_module.recalibrate_polar_model(spec)

            self.assertEqual(report["status"], "BLOCKED")
            self.assertIn("model_metadata", report)
            blocker_codes = {b["code"] for b in report["blockers"]}
            self.assertIn("DETECTION_VERIFICATION_FAILED", blocker_codes)

            report_path = output_dir / "report.json"
            self.assertTrue(report_path.is_file())
            failure_path = output_dir / "failure-list.json"
            self.assertTrue(failure_path.is_file())


if __name__ == "__main__":
    unittest.main()
