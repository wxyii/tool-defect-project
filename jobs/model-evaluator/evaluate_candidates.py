"""三组历史双任务候选的独立、受控技术评估。"""

from dataclasses import dataclass
import csv
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import sys
import time
from typing import Any, Callable, Iterable

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

@dataclass(frozen=True)
class CandidateSpec:
    candidate_id: str
    model_dir: Path
    config_path: Path
    expected_model_sha256: str
    expected_weights_sha256: str
    fixed_test_manifest_path: Path | None = None

    def __post_init__(self) -> None:
        if re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,63}", self.candidate_id
        ) is None:
            raise ValueError("候选标识格式非法")
        if not isinstance(self.model_dir, Path) or not isinstance(
            self.config_path, Path
        ):
            raise TypeError("候选模型和配置路径必须使用 Path")
        if (
            self.fixed_test_manifest_path is not None
            and not isinstance(self.fixed_test_manifest_path, Path)
        ):
            raise TypeError("固定测试清单路径必须使用 Path")


def documented_candidate_specs(
    project_root: Path,
) -> tuple[CandidateSpec, ...]:
    root = Path(project_root)
    model_root = _candidate_model_root(root)
    architecture = (
        "63870f093b42ae0b51617cf0dd83465c122b49222e7e8e80db4f6c855b77d4b3"
    )
    return (
        CandidateSpec(
            candidate_id="multitask",
            model_dir=model_root / "multitask",
            config_path=root / "configs/retrain_multitask.json",
            expected_model_sha256=architecture,
            expected_weights_sha256=(
                "5613d2eb4dabcc691e114fd921f5bb8f6d9d5a5a561bd8232dd58f1ece248f7a"
            ),
            fixed_test_manifest_path=(
                root / "data/manifests/retrain.csv"
            ),
        ),
        CandidateSpec(
            candidate_id="multitask_adaptive_annular",
            model_dir=model_root / "multitask_adaptive_annular",
            config_path=root / "configs/multitask_adaptive_annular.json",
            expected_model_sha256=architecture,
            expected_weights_sha256=(
                "35f64b4a9545afe8564a69e9b9ba8d4dc305729f51977c495ab033f95e96a98e"
            ),
            fixed_test_manifest_path=(
                root / "data/manifests/retrain.csv"
            ),
        ),
        CandidateSpec(
            candidate_id="multitask_boundary_normalized",
            model_dir=model_root / "multitask_boundary_normalized",
            config_path=root / "configs/multitask_boundary_normalized.json",
            expected_model_sha256=architecture,
            expected_weights_sha256=(
                "162526a04bc4972faff9fff13f77b37e4a3509884d33aa188303ae5b855ca545"
            ),
            fixed_test_manifest_path=(
                root / "data/manifests/retrain.csv"
            ),
        ),
    )


def _candidate_model_root(project_root: Path) -> Path:
    canonical = project_root / "outputs/training"
    migration_staging = project_root / "training"
    if canonical.is_dir():
        return canonical
    if migration_staging.is_dir():
        return migration_staging
    return canonical


def evaluate_three_candidates(
    specs: Iterable[CandidateSpec],
    output_dir: Path,
    *,
    evaluator: Callable[..., dict] | None = None,
    bootstrap_samples: int = 1000,
    seed: int = 1,
) -> dict[str, Any]:
    specs = tuple(specs)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    identifiers = [spec.candidate_id for spec in specs]
    if len(specs) != 3 or len(set(identifiers)) != 3:
        raise ValueError("技术评估必须包含三个唯一候选")
    if (
        isinstance(bootstrap_samples, bool)
        or not isinstance(bootstrap_samples, int)
        or bootstrap_samples <= 0
    ):
        raise ValueError("自助法采样次数必须是正整数")

    audits = [_audit_candidate(spec) for spec in specs]
    blockers = [
        blocker
        for audit in audits
        for blocker in audit["blockers"]
    ]
    test_sets: dict[str, list[str]] = {}
    evaluation_manifests: dict[str, Path] = {}
    for spec, audit in zip(specs, audits):
        try:
            sample_ids = _test_sample_ids(
                spec.config_path,
                spec.fixed_test_manifest_path,
            )
        except Exception as error:
            blockers.append(
                {
                    "candidate_id": spec.candidate_id,
                    "code": "TEST_MANIFEST_INVALID",
                    "message": "无法读取候选测试清单",
                    "exception_type": type(error).__name__,
                }
            )
            continue
        test_sets[spec.candidate_id] = sample_ids
        if spec.fixed_test_manifest_path is not None:
            try:
                prepared = _prepare_evaluation_manifest(
                    spec,
                    sample_ids,
                    output_dir,
                )
            except Exception as error:
                blockers.append(
                    {
                        "candidate_id": spec.candidate_id,
                        "code": "EVALUATION_MANIFEST_INVALID",
                        "message": "无法构建候选专属固定评估清单",
                        "exception_type": type(error).__name__,
                    }
                )
            else:
                evaluation_manifests[spec.candidate_id] = prepared["path"]
                audit["evaluation_input"] = {
                    key: value
                    for key, value in prepared.items()
                    if key != "path"
                }
        if len(sample_ids) != 34:
            blockers.append(
                {
                    "candidate_id": spec.candidate_id,
                    "code": "TEST_SAMPLE_COUNT_MISMATCH",
                    "message": "候选测试集不是固定 34 张",
                    "actual": len(sample_ids),
                }
            )
        if any(not isinstance(sample_id, str) or not sample_id for sample_id in sample_ids):
            blockers.append(
                {
                    "candidate_id": spec.candidate_id,
                    "code": "TEST_SAMPLE_ID_INVALID",
                    "message": "候选测试集包含空或非字符串样本标识",
                }
            )
        if len(set(sample_ids)) != len(sample_ids):
            blockers.append(
                {
                    "candidate_id": spec.candidate_id,
                    "code": "TEST_SAMPLE_ID_DUPLICATE",
                    "message": "候选测试集包含重复样本标识",
                }
            )
    reference_ids = test_sets.get(specs[0].candidate_id)
    if reference_ids is not None:
        for spec in specs[1:]:
            sample_ids = test_sets.get(spec.candidate_id)
            if sample_ids is not None and sample_ids != reference_ids:
                blockers.append(
                    {
                        "candidate_id": spec.candidate_id,
                        "code": "TEST_SAMPLE_ORDER_MISMATCH",
                        "message": "候选测试集样本或顺序不一致",
                        "reference_candidate_id": specs[0].candidate_id,
                    }
                )

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "evaluation_kind": "THREE_INDEPENDENT_MULTITASK_CANDIDATES",
        "candidate_count": 3,
        "fixed_test_samples_required": 34,
        "candidates": audits,
        "production_claim_allowed": False,
    }
    if blockers:
        report["status"] = "BLOCKED"
        report["blockers"] = blockers
        _write_reports(output_dir, report, blockers)
        return report

    if evaluator is None:
        evaluator = _default_evaluator
    results = []
    for spec in specs:
        candidate_output = output_dir / spec.candidate_id
        try:
            started = time.perf_counter()
            resource_before = _peak_rss()
            evaluator_arguments = {
                "task": "multitask",
                "config_path": spec.config_path,
                "model_dir": spec.model_dir,
                "split": "test",
                "output_dir": candidate_output,
                "full_metrics": True,
            }
            if spec.candidate_id in evaluation_manifests:
                evaluator_arguments["manifest_path"] = (
                    evaluation_manifests[spec.candidate_id]
                )
            metrics = evaluator(
                **evaluator_arguments,
            )
            elapsed = time.perf_counter() - started
            _validate_metrics(metrics)
            predictions_path = candidate_output / "predictions.csv"
            intervals = _bootstrap_intervals(
                predictions_path,
                expected_sample_ids=test_sets[spec.candidate_id],
                samples=bootstrap_samples,
                seed=seed,
            )
            result = {
                "candidate_id": spec.candidate_id,
                "classification": _json_value(
                    metrics["classification"]
                ),
                "segmentation": _json_value(metrics["segmentation"]),
                "classification_accuracy": float(
                    metrics["classification_accuracy"]
                ),
                "mean_iou": float(metrics["mean_iou"]),
                "total_standardized_loss": float(
                    metrics["total_standardized_loss"]
                ),
                "bootstrap_95_ci": intervals,
                "runtime": {
                    "wall_seconds": elapsed,
                    "peak_rss_before": resource_before,
                    "peak_rss_after": _peak_rss(),
                    "gpu_memory_bytes": None,
                    "gpu_measurement_status": "NOT_MEASURED",
                },
                "artifact": {
                    "model_json_sha256": spec.expected_model_sha256,
                    "weights_h5_sha256": spec.expected_weights_sha256,
                    "predictions_csv_sha256": _file_sha256(
                        predictions_path
                    ),
                },
                "candidate_status": "TEST_CANDIDATE",
                "production_claim_allowed": False,
            }
        except Exception as error:
            blockers.append(
                {
                    "candidate_id": spec.candidate_id,
                    "code": "EVALUATION_FAILED",
                    "message": "候选独立评估失败，未生成该候选指标",
                    "exception_type": type(error).__name__,
                }
            )
            continue
        results.append(result)
        candidate_output.mkdir(parents=True, exist_ok=True)
        (candidate_output / "candidate-report.json").write_text(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
    if blockers:
        report.update(
            {
                "status": "BLOCKED",
                "blockers": blockers,
                "completed_candidate_results": results,
            }
        )
        _write_reports(output_dir, report, blockers)
        return report
    report.update(
        {
            "status": "COMPLETE",
            "results": results,
            "shared_test_sample_ids": next(iter(test_sets.values())),
        }
    )
    _write_reports(output_dir, report, [])
    return report


def _audit_candidate(spec: CandidateSpec) -> dict[str, Any]:
    blockers = []
    files = {
        "model.json": spec.expected_model_sha256,
        "weights.h5": spec.expected_weights_sha256,
    }
    observed = {}
    for name, expected in files.items():
        path = spec.model_dir / name
        if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            blockers.append(
                {
                    "candidate_id": spec.candidate_id,
                    "code": "EXPECTED_HASH_INVALID",
                    "file": name,
                    "message": "候选登记哈希格式非法",
                }
            )
            continue
        if not path.is_file():
            blockers.append(
                {
                    "candidate_id": spec.candidate_id,
                    "code": "MODEL_FILE_MISSING",
                    "file": _display_path(path),
                    "message": "候选模型文件缺失",
                }
            )
            continue
        actual = _file_sha256(path)
        observed[name] = actual
        if actual != expected:
            blockers.append(
                {
                    "candidate_id": spec.candidate_id,
                    "code": "MODEL_HASH_MISMATCH",
                    "file": _display_path(path),
                    "expected": expected,
                    "actual": actual,
                    "message": "候选模型文件哈希不匹配",
                }
            )
    if not spec.config_path.is_file():
        blockers.append(
            {
            "candidate_id": spec.candidate_id,
            "code": "CONFIG_MISSING",
            "file": _display_path(spec.config_path),
                "message": "候选评估配置缺失",
            }
        )
    else:
        observed["evaluation_config"] = _file_sha256(
            spec.config_path
        )
    return {
        "candidate_id": spec.candidate_id,
        "model_dir": _display_path(spec.model_dir),
        "config_path": _display_path(spec.config_path),
        "expected": files,
        "observed": observed,
        "status": "VERIFIED" if not blockers else "BLOCKED",
        "blockers": blockers,
    }


def _test_sample_ids(
    config_path: Path,
    fixed_test_manifest_path: Path | None = None,
) -> list[str]:
    from tool_defect.config import load_config

    config = load_config(config_path)
    manifest_path = fixed_test_manifest_path or config.path("manifest")
    with manifest_path.open(
        newline="", encoding="utf-8-sig"
    ) as handle:
        return [
            row["sample_id"]
            for row in csv.DictReader(handle)
            if row["split"] == "test"
        ]


def _prepare_evaluation_manifest(
    spec: CandidateSpec,
    expected_sample_ids: list[str],
    output_dir: Path,
) -> dict[str, Any]:
    from tool_defect.config import load_config

    if spec.fixed_test_manifest_path is None:
        raise ValueError("候选没有登记固定测试清单")
    config = load_config(spec.config_path)
    source_manifest = config.path("manifest")
    fixed_manifest = spec.fixed_test_manifest_path
    source_fields, source_rows = _read_manifest(source_manifest)
    _, fixed_rows = _read_manifest(fixed_manifest)
    required_fields = {
        "sample_id",
        "image_path",
        "mask_path",
        "label",
        "label_name",
        "split",
    }
    if not required_fields.issubset(source_fields):
        raise ValueError("候选源清单缺少评估所需字段")
    source_by_id = _unique_rows_by_sample_id(source_rows, "候选源清单")
    fixed_by_id = _unique_rows_by_sample_id(fixed_rows, "固定测试清单")
    fixed_ids = [
        row["sample_id"] for row in fixed_rows if row["split"] == "test"
    ]
    if fixed_ids != expected_sample_ids:
        raise ValueError("固定测试清单在派生期间发生变化")
    selected_rows = []
    data_root = config.path("data").resolve()
    for sample_id in expected_sample_ids:
        if sample_id not in source_by_id or sample_id not in fixed_by_id:
            raise ValueError("候选源清单缺少固定测试样本")
        source_row = source_by_id[sample_id]
        fixed_row = fixed_by_id[sample_id]
        for field in ("label", "label_name"):
            if source_row[field] != fixed_row[field]:
                raise ValueError("候选源清单与固定测试标签不一致")
        for field in ("image_path", "mask_path"):
            relative_path = source_row[field]
            candidate_path = Path(relative_path)
            if (
                not relative_path
                or candidate_path.is_absolute()
                or PureWindowsPath(relative_path).is_absolute()
            ):
                raise ValueError("候选源清单包含非法文件路径")
            resolved_path = (data_root / candidate_path).resolve()
            try:
                resolved_path.relative_to(data_root)
            except ValueError as error:
                raise ValueError("候选源清单文件路径越界") from error
            if not resolved_path.is_file():
                raise ValueError("候选固定测试图片或掩膜缺失")
        selected = dict(source_row)
        selected["split"] = "test"
        selected_rows.append(selected)

    manifest_dir = Path(output_dir) / "evaluation-manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    destination = manifest_dir / f"{spec.candidate_id}.csv"
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=source_fields)
        writer.writeheader()
        writer.writerows(selected_rows)
    return {
        "path": destination,
        "manifest": _display_path(destination),
        "manifest_sha256": _file_sha256(destination),
        "source_manifest": _display_path(source_manifest),
        "source_manifest_sha256": _file_sha256(source_manifest),
        "fixed_test_manifest": _display_path(fixed_manifest),
        "fixed_test_manifest_sha256": _file_sha256(fixed_manifest),
        "sample_count": len(selected_rows),
    }


def _read_manifest(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("清单没有表头")
        return list(reader.fieldnames), list(reader)


def _unique_rows_by_sample_id(
    rows: list[dict[str, str]],
    description: str,
) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        sample_id = row.get("sample_id", "")
        if not sample_id:
            raise ValueError(f"{description}包含空样本标识")
        if sample_id in indexed:
            raise ValueError(f"{description}包含重复样本标识")
        indexed[sample_id] = row
    return indexed


def _bootstrap_intervals(
    predictions_path: Path,
    *,
    expected_sample_ids: list[str],
    samples: int,
    seed: int,
) -> dict[str, dict[str, float]]:
    with predictions_path.open(
        newline="", encoding="utf-8-sig"
    ) as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 34:
        raise ValueError("逐图预测结果必须恰好包含 34 张固定测试图")
    required = {
        "sample_id",
        "true_label",
        "predicted_label",
        "defect_iou",
        "defect_dice",
    }
    if not rows or not required.issubset(rows[0]):
        raise ValueError("逐图预测结果缺少分类或分割字段")
    observed_sample_ids = [row["sample_id"] for row in rows]
    if len(set(observed_sample_ids)) != len(observed_sample_ids):
        raise ValueError("逐图预测结果包含重复 sample_id")
    if observed_sample_ids != expected_sample_ids:
        raise ValueError("逐图预测 sample_id 与冻结测试清单或顺序不一致")
    correct = np.asarray(
        [row["true_label"] == row["predicted_label"] for row in rows],
        dtype=np.float64,
    )
    iou = np.asarray([float(row["defect_iou"]) for row in rows])
    dice = np.asarray([float(row["defect_dice"]) for row in rows])
    if (
        not np.all(np.isfinite(iou))
        or not np.all(np.isfinite(dice))
        or np.any(iou < 0.0)
        or np.any(iou > 1.0)
        or np.any(dice < 0.0)
        or np.any(dice > 1.0)
    ):
        raise ValueError("逐图分割指标必须是 0 到 1 的有限值")
    randomizer = np.random.default_rng(seed)
    indexes = randomizer.integers(
        0, len(rows), size=(int(samples), len(rows))
    )
    values = {
        "classification_accuracy": np.mean(correct[indexes], axis=1),
        "per_image_defect_iou_mean": np.mean(iou[indexes], axis=1),
        "per_image_defect_dice_mean": np.mean(dice[indexes], axis=1),
    }
    return {
        name: {
            "lower": float(np.quantile(distribution, 0.025)),
            "upper": float(np.quantile(distribution, 0.975)),
        }
        for name, distribution in values.items()
    }


def _write_reports(
    output_dir: Path,
    report: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    (output_dir / "evaluation-report.json").write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "failure-list.json").write_text(
        json.dumps(
            {
                "status": "BLOCKED" if blockers else "EMPTY",
                "failure_count": len(blockers),
                "failures": blockers,
            },
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _peak_rss() -> dict[str, Any]:
    try:
        import resource

        return {
            "value": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "unit": "platform_ru_maxrss",
        }
    except (ImportError, OSError):
        return {"value": None, "unit": "UNAVAILABLE"}


def _default_evaluator(**kwargs) -> dict:
    from tool_defect.evaluation.evaluate import evaluate

    return evaluate(**kwargs)


def _validate_metrics(metrics: Any) -> None:
    required = {
        "classification",
        "segmentation",
        "classification_accuracy",
        "mean_iou",
        "total_standardized_loss",
    }
    if not isinstance(metrics, dict) or not required.issubset(metrics):
        raise ValueError("评估器没有返回完整分类与分割指标")
    for name in (
        "classification_accuracy",
        "mean_iou",
        "total_standardized_loss",
    ):
        if not np.isfinite(float(metrics[name])):
            raise ValueError(f"评估指标不是有限值：{name}")
    for name in ("classification_accuracy", "mean_iou"):
        if not 0.0 <= float(metrics[name]) <= 1.0:
            raise ValueError(f"评估指标超出 0 到 1：{name}")
    if float(metrics["total_standardized_loss"]) < 0.0:
        raise ValueError("标准化损失不能为负数")


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _json_value(nested)
            for key, nested in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(nested) for nested in value]
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        raise ValueError("评估指标包含非有限浮点数")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"评估指标包含不可序列化类型：{type(value).__name__}")


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="评估三个历史双任务候选")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = evaluate_three_candidates(
        documented_candidate_specs(args.project_root),
        args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
