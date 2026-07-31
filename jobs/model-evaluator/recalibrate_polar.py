"""P6-04 极坐标模型重标定脚本。

使用代码级缓存和无标签标定生成版本 2 极坐标异常模型；
拒绝旧版本 1 模型，并输出受控评估报告。
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from tool_defect.detection.polar_anomaly import (
    FEATURE_NAMES,
    MODEL_VERSION,
    PolarAnomalyModel,
    fit_unlabeled_model,
    iter_image_paths,
    run_detection,
)
from tool_defect.detection.polar_cache import source_root_for

LEGACY_VERSION = 1
FIXED_TEST_SAMPLE_COUNT = 34


@dataclass(frozen=True)
class RecalibrationSpec:
    """稳态重标定规格，所有配置来源可审计。"""

    spec_id: str
    input_dir: Path
    cache_dir: Path
    output_dir: Path
    legacy_model_path: Path | None = None
    output_size: int = 512
    angle_samples: int = 1440
    minimum_periods: int = 8
    maximum_periods: int = 40

    def __post_init__(self):
        if not self.input_dir.is_dir():
            raise FileNotFoundError(f"输入目录不存在：{self.input_dir}")
        if self.legacy_model_path is not None:
            resolved = self.legacy_model_path.resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"旧模型不存在：{resolved}")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _audit_legacy_model(model_path: Path) -> dict[str, Any] | None:
    """检查是否存在旧版本模型并返回阻隔信息，若无则返回 None。"""
    try:
        model_data = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取旧模型文件：{model_path}") from error

    observed_version = int(model_data.get("version", -1))
    if observed_version == MODEL_VERSION:
        raise ValueError("旧模型版本号与当前代码一致，无需重标定")

    blockers = []
    if observed_version == LEGACY_VERSION:
        blockers.append(
            {
                "code": "LEGACY_VERSION_REJECTED",
                "message": f"版本 {LEGACY_VERSION} 模型已弃用，当前代码要求版本 {MODEL_VERSION}",
                "legacy_version": LEGACY_VERSION,
                "required_version": MODEL_VERSION,
                "model_path": _display_path(model_path),
            }
        )
    else:
        blockers.append(
            {
                "code": "UNRECOGNIZED_VERSION",
                "message": f"无法识别的模型版本：{observed_version}",
                "observed_version": observed_version,
                "required_version": MODEL_VERSION,
                "model_path": _display_path(model_path),
            }
        )

    legacy_audit: dict[str, Any] = {
        "model_path": _display_path(model_path),
        "model_sha256": _file_sha256(model_path),
        "observed_version": observed_version,
        "expected_version": LEGACY_VERSION,
        "required_version": MODEL_VERSION,
        "status": "REJECTED",
        "blockers": blockers,
    }

    missing_keys = {
        "feature_centers",
        "feature_scales",
        "threshold",
    }.difference(model_data)
    if missing_keys:
        blockers.append(
            {
                "code": "LEGACY_MODEL_CORRUPTED",
                "message": f"旧模型缺少必要字段：{sorted(missing_keys)}",
                "missing_fields": sorted(missing_keys),
            }
        )

    try:
        PolarAnomalyModel.load(model_path)
    except ValueError:
        pass
    else:
        blockers.append(
            {
                "code": "LEGACY_MODEL_LOADED",
                "message": f"版本 {LEGACY_VERSION} 模型意外通过了版本 {MODEL_VERSION} 的加载校验",
                "legacy_version": LEGACY_VERSION,
                "current_version": MODEL_VERSION,
            }
        )

    return legacy_audit


def _image_statistics(image_paths: list[Path]) -> dict[str, Any]:
    total_size = 0
    stems = []
    extensions: dict[str, int] = {}
    for image_path in image_paths:
        total_size += image_path.stat().st_size
        stems.append(image_path.stem)
        ext = image_path.suffix.lower()
        extensions[ext] = extensions.get(ext, 0) + 1
    return {
        "count": len(image_paths),
        "total_bytes": total_size,
        "extensions": extensions,
        "first_three_stems": stems[:3],
        "last_three_stems": stems[-3:] if len(stems) > 3 else stems,
    }


def _test_set_mapping(image_paths: list[Path]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for index, image_path in enumerate(image_paths):
        stem = f"{index:04d}_{image_path.stem}"
        mapping[stem] = {
            "index": index,
            "source": _display_path(image_path),
            "source_sha256": _file_sha256(image_path),
            "size": image_path.stat().st_size,
        }
    return mapping


def recalibrate_polar_model(spec: RecalibrationSpec) -> dict[str, Any]:
    """执行极坐标模型重标定并生成完整评估报告。"""
    started = time.perf_counter()
    output_dir = Path(spec.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"不可变重标定输出已存在，拒绝覆盖：{output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    blockers: list[dict[str, Any]] = []
    legacy_blockers: list[dict[str, Any]] = []
    provenance: dict[str, Any] = {
        "schema_version": "1.0",
        "recalibration_type": "POLAR_V2_CODE_BASED_CACHE_AND_LABEL_FREE",
        "spec_id": spec.spec_id,
        "target_model_version": MODEL_VERSION,
        "output_size": spec.output_size,
        "angle_samples": spec.angle_samples,
        "minimum_periods": spec.minimum_periods,
        "maximum_periods": spec.maximum_periods,
        "immutable": True,
        "production_claim_allowed": False,
    }

    if spec.legacy_model_path is not None:
        try:
            legacy_audit = _audit_legacy_model(spec.legacy_model_path)
            provenance["legacy_model"] = legacy_audit
            legacy_blockers = legacy_audit.get("blockers", [])
        except Exception as error:
            legacy_blockers = [
                {
                    "code": "LEGACY_AUDIT_FAILED",
                    "message": str(error),
                    "exception_type": type(error).__name__,
                }
            ]

    image_paths = iter_image_paths(spec.input_dir)
    if not image_paths:
        raise FileNotFoundError(f"输入目录中没有可用图像：{spec.input_dir}")

    provenance["input_images"] = _image_statistics(image_paths)

    if len(image_paths) != FIXED_TEST_SAMPLE_COUNT:
        blockers.append(
            {
                "code": "TEST_SAMPLE_COUNT_MISMATCH",
                "message": f"输入图像不是固定 {FIXED_TEST_SAMPLE_COUNT} 张",
                "actual": len(image_paths),
                "expected": FIXED_TEST_SAMPLE_COUNT,
            }
        )

    test_mapping = _test_set_mapping(image_paths)
    provenance["test_set"] = {
        "sample_count": len(test_mapping),
        "mapping": test_mapping,
    }

    report: dict[str, Any] = {
        "schema_version": "2.0",
        "recalibration_kind": "POLAR_ANOMALY_V2_FROM_CODE",
        "model_version_target": MODEL_VERSION,
        "production_claim_allowed": False,
        "provenance": provenance,
        "fixed_test_samples_required": FIXED_TEST_SAMPLE_COUNT,
    }

    if blockers:
        report["status"] = "BLOCKED"
        report["blockers"] = blockers
        _write_reports(output_dir, report, blockers)
        return report

    model_output = output_dir / "model"
    model_output.mkdir(parents=True, exist_ok=True)

    calibration_started = time.perf_counter()
    try:
        model, calibration_report = fit_unlabeled_model(
            spec.input_dir,
            model_output,
            output_size=spec.output_size,
            angle_samples=spec.angle_samples,
            minimum_periods=spec.minimum_periods,
            maximum_periods=spec.maximum_periods,
            cache_dir=spec.cache_dir,
        )
    except Exception as error:
        blockers.append(
            {
                "code": "CALIBRATION_FAILED",
                "message": str(error),
                "exception_type": type(error).__name__,
            }
        )
        report["status"] = "BLOCKED"
        report["blockers"] = blockers
        _write_reports(output_dir, report, blockers)
        return report

    calibration_elapsed = time.perf_counter() - calibration_started

    if model.version != MODEL_VERSION:
        blockers.append(
            {
                "code": "VERSION_MISMATCH_AFTER_CALIBRATION",
                "message": f"标定产物版本为 {model.version}，但要求 {MODEL_VERSION}",
                "actual": model.version,
                "expected": MODEL_VERSION,
            }
        )
        report["status"] = "BLOCKED"
        report["blockers"] = blockers
        _write_reports(output_dir, report, blockers)
        return report

    model.save(model_output)
    model_path = model_output / "polar_anomaly.json"

    detection_output = output_dir / "detection"
    detection_output.mkdir(parents=True, exist_ok=True)

    detection_started = time.perf_counter()
    try:
        detection_report = run_detection(
            spec.input_dir,
            model_path,
            detection_output,
            cache_dir=spec.cache_dir,
        )
    except Exception as error:
        blockers.append(
            {
                "code": "DETECTION_VERIFICATION_FAILED",
                "message": str(error),
                "exception_type": type(error).__name__,
            }
        )
    detection_elapsed = time.perf_counter() - detection_started

    recalibration_metrics = {
        "calibration": {
            "input_images": calibration_report.get("input_images", 0),
            "calibration_images": calibration_report.get("calibration_images", 0),
            "failed_images": calibration_report.get("failed_images", 0),
            "threshold": calibration_report.get("threshold", model.threshold),
            "period_counts": calibration_report.get("period_counts", {}),
            "cache_hits": calibration_report.get("cache_hits", 0),
            "cache_rebuilt": calibration_report.get("cache_rebuilt", 0),
            "wall_seconds": calibration_elapsed,
        },
        "detection": {
            "input_images": detection_report.get("input_images", 0)
            if not blockers
            else 0,
            "successful_images": detection_report.get("successful_images", 0)
            if not blockers
            else 0,
            "failed_images": detection_report.get("failed_images", 0)
            if not blockers
            else 0,
            "images_with_regions": detection_report.get(
                "images_with_regions", 0
            )
            if not blockers
            else 0,
            "wall_seconds": detection_elapsed if not blockers else 0.0,
        },
    }
    if not blockers and detection_report.get("score_distribution"):
        recalibration_metrics["detection"][
            "score_distribution"
        ] = detection_report["score_distribution"]

    feature_centers = dict(zip(FEATURE_NAMES, model.feature_centers))
    feature_scales = dict(zip(FEATURE_NAMES, model.feature_scales))

    model_metadata = {
        "version": model.version,
        "threshold": model.threshold,
        "output_size": model.output_size,
        "angle_samples": model.angle_samples,
        "minimum_periods": model.minimum_periods,
        "maximum_periods": model.maximum_periods,
        "calibration_images": model.calibration_images,
        "failed_images": model.failed_images,
        "feature_centers": feature_centers,
        "feature_scales": feature_scales,
        "model_sha256": _file_sha256(model_path),
        "model_path": _display_path(model_path),
    }

    elapsed = time.perf_counter() - started
    if blockers:
        report["status"] = "BLOCKED"
        report["blockers"] = blockers
        report["model_metadata"] = model_metadata
        report["recalibration_metrics"] = recalibration_metrics
    else:
        report["status"] = "COMPLETE"
        report["model_metadata"] = model_metadata
        report["recalibration_metrics"] = recalibration_metrics

    if legacy_blockers:
        report["legacy_model_blockers"] = legacy_blockers

    report["runtime"] = {
        "wall_seconds": elapsed,
        "calibration_wall_seconds": calibration_elapsed,
        "detection_wall_seconds": detection_elapsed if not blockers else 0.0,
    }

    _write_reports(output_dir, report, blockers, legacy_blockers)
    return report


def _write_reports(
    output_dir: Path,
    report: dict[str, Any],
    blockers: list[dict[str, Any]],
    legacy_blockers: list[dict[str, Any]] | None = None,
) -> None:
    report_path = output_dir / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )

    provenance_payload = dict(report.get("provenance", {}))
    provenance_path = output_dir / "provenance.json"
    provenance_payload["report_sha256"] = _file_sha256(report_path)
    provenance_payload["generated_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
    )
    provenance_payload["production_claim_allowed"] = False
    provenance_path.write_text(
        json.dumps(
            provenance_payload, ensure_ascii=False, indent=2, allow_nan=False
        ),
        encoding="utf-8",
    )

    all_failures = list(blockers)
    if legacy_blockers:
        all_failures.extend(legacy_blockers)
    failure_path = output_dir / "failure-list.json"
    failure_payload = {
        "status": "BLOCKED" if all_failures else "EMPTY",
        "failure_count": len(all_failures),
        "failures": all_failures,
        "legacy_blockers": legacy_blockers or [],
        "production_claim_allowed": False,
    }
    failure_path.write_text(
        json.dumps(
            failure_payload, ensure_ascii=False, indent=2, allow_nan=False
        ),
        encoding="utf-8",
    )

    test_data_dir = output_dir / "test-data"
    test_data_dir.mkdir(parents=True, exist_ok=True)

    def _np_encoder(obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return _np_encoder(obj.tolist())
        if isinstance(obj, (list, tuple)):
            return [_np_encoder(item) for item in obj]
        if isinstance(obj, dict):
            return {str(k): _np_encoder(v) for k, v in obj.items()}
        if isinstance(obj, (int, float, str, bool)) or obj is None:
            return obj
        raise TypeError(f"{type(obj).__name__} 无法序列化")

    if "model_metadata" in report:
        test_data = {
            "model_version": report["model_metadata"]["version"],
            "threshold": report["model_metadata"]["threshold"],
            "feature_centers": _np_encoder(
                report["model_metadata"]["feature_centers"]
            ),
            "feature_scales": _np_encoder(
                report["model_metadata"]["feature_scales"]
            ),
            "production_claim_allowed": False,
        }
        (test_data_dir / "model-snapshot.json").write_text(
            json.dumps(test_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    test_mapping = provenance_payload.get("test_set", {}).get("mapping", {})
    if test_mapping:
        test_set_stems = list(test_mapping)[:]
        (test_data_dir / "test-set-ids.json").write_text(
            json.dumps(
                {
                    "sample_count": len(test_set_stems),
                    "sample_ids": test_set_stems,
                    "fixed_count": FIXED_TEST_SAMPLE_COUNT,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="P6-04 极坐标模型重标定")
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="输入图像目录",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="受控输出根目录",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        required=True,
        help="预处理缓存目录",
    )
    parser.add_argument(
        "--legacy-model",
        type=Path,
        default=None,
        help="需要替换的旧版本模型文件路径",
    )
    parser.add_argument(
        "--output-size",
        type=int,
        default=512,
        help="极坐标输出尺寸",
    )
    parser.add_argument(
        "--angle-samples",
        type=int,
        default=1440,
        help="角度采样数",
    )
    args = parser.parse_args(argv)

    spec = RecalibrationSpec(
        spec_id="polar-v2-recalibration",
        input_dir=args.input_dir,
        cache_dir=args.cache_dir,
        output_dir=args.output_dir,
        legacy_model_path=args.legacy_model,
        output_size=args.output_size,
        angle_samples=args.angle_samples,
    )

    report = recalibrate_polar_model(spec)
    print(
        json.dumps(
            {
                "status": report["status"],
                "schema_version": report["schema_version"],
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
