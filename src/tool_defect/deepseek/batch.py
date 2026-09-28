"""批量调用 DeepSeek 并与现有算法结果做父图级对比。"""

import csv
import json
import os
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".gif", ".webp"}
LABEL_ALIASES = {
    "qualified": 0,
    "合格": 0,
    "good": 0,
    "0": 0,
    "unqualified": 1,
    "不合格": 1,
    "bad": 1,
    "1": 1,
}
PREDICTION_FIELDS = [
    "image_path",
    "has_defect",
    "image_quality",
    "certainty",
    "defect_count",
    "defects_json",
    "decision_candidate",
    "baseline_predicted_class",
    "baseline_conflict",
    "error",
    "run_id",
    "run_started_at",
    "model",
    "response_id",
    "elapsed_seconds",
    "ground_truth_label",
]


def discover_images(input_paths: Iterable[Path]):
    paths = []
    for item in input_paths:
        path = Path(item)
        if path.is_file():
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                raise ValueError(f"不支持的图片格式: {path}")
            paths.append(path)
        elif path.is_dir():
            paths.extend(
                sorted(
                    (
                        candidate
                        for candidate in path.rglob("*")
                        if candidate.is_file()
                        and candidate.suffix.lower() in IMAGE_SUFFIXES
                    ),
                    key=lambda candidate: str(candidate).lower(),
                )
            )
        else:
            raise FileNotFoundError(path)
    if not paths:
        raise ValueError("没有发现可用图片")
    return paths


def _keys(path_value: str):
    path = Path(path_value)
    try:
        yield str(path.resolve()).lower()
    except OSError:
        pass
    yield path.name.lower()
    yield path.stem.lower()


def _read_csv_index(csv_path: Optional[Path], label_mode: bool = False):
    if csv_path is None:
        return {}
    index = {}
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            image_value = (
                row.get("image_path") or row.get("path") or row.get("filename")
            )
            if not image_value:
                continue
            value = (
                row.get("label") or row.get("label_name")
                if label_mode
                else row.get("predicted_class")
            )
            if value is None and not label_mode:
                value = row.get("predicted_label")
            if value is None:
                continue
            if label_mode:
                normalised = LABEL_ALIASES.get(str(value).strip().lower())
                if normalised is None:
                    continue
                value = normalised
            for key in _keys(image_value):
                index.setdefault(key, value)
    return index


def _baseline_label(row_value: Any):
    if row_value is None:
        return None
    return LABEL_ALIASES.get(str(row_value).strip().lower())


def _first_not_none(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _candidate_decision(parsed: Dict[str, Any], baseline_label: Optional[int]):
    if parsed["has_defect"] == "yes":
        candidate = "unqualified_candidate"
    elif (
        parsed["has_defect"] == "no"
        and parsed["image_quality"] == "usable"
        and parsed["certainty"] == "high"
    ):
        candidate = "qualified_candidate"
    else:
        candidate = "manual_review_candidate"
    model_label = {"no": 0, "yes": 1}.get(parsed["has_defect"])
    conflict = (
        baseline_label is not None
        and model_label is not None
        and baseline_label != model_label
    )
    if conflict:
        candidate = "manual_review_candidate"
    return candidate, model_label, conflict


def _binary_metrics(pairs):
    if not pairs:
        return {"samples": 0, "coverage": 0.0}
    tp = sum(pred == 1 and truth == 1 for pred, truth in pairs)
    tn = sum(pred == 0 and truth == 0 for pred, truth in pairs)
    fp = sum(pred == 1 and truth == 0 for pred, truth in pairs)
    fn = sum(pred == 0 and truth == 1 for pred, truth in pairs)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    accuracy = (tp + tn) / len(pairs)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "samples": len(pairs),
        "coverage": len(pairs),
        "accuracy": round(accuracy, 6),
        "unqualified_precision": round(precision, 6),
        "unqualified_recall": round(recall, 6),
        "unqualified_f1": round(f1, 6),
        "confusion_matrix": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
    }


def _read_prediction_rows(prediction_path: Path):
    if not prediction_path.is_file() or prediction_path.stat().st_size == 0:
        return []
    with prediction_path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _write_prediction_csv(path: Path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _append_prediction_rows(path: Path, rows):
    """追加预测记录；旧 CSV 缺少新增字段时先安全扩展表头。"""

    existing_rows = _read_prediction_rows(path)
    existing_fields = []
    if path.is_file() and path.stat().st_size:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            existing_fields = next(csv.reader(handle), [])

    fieldnames = existing_fields or list(PREDICTION_FIELDS)
    for field in PREDICTION_FIELDS:
        if field not in fieldnames:
            fieldnames.append(field)

    if existing_rows or not existing_fields:
        _write_prediction_csv(path, fieldnames, [*existing_rows, *rows])
    else:
        # 只有表头没有数据时也统一写入当前字段集合。
        _write_prediction_csv(path, fieldnames, rows)


def _stored_label(value: Any):
    if value is None or str(value).strip() == "":
        return None
    return _baseline_label(value)


def _metrics_from_rows(rows, prediction_field: str):
    pairs = []
    for row in rows:
        truth = _stored_label(row.get("ground_truth_label"))
        if truth is None:
            continue
        if prediction_field == "has_defect":
            prediction = {"no": 0, "yes": 1}.get(row.get(prediction_field))
        else:
            prediction = _baseline_label(row.get(prediction_field))
        if prediction is not None:
            pairs.append((prediction, truth))
    return _binary_metrics(pairs)


def _safe_error_text(error: Exception):
    text = f"{type(error).__name__}: {error}"
    return re.sub(r"sk-[A-Za-z0-9_-]+", "<REDACTED>", text)


def _new_run_id(started_at: datetime):
    return f"{started_at.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}"


def _append_report(report_path: Path, run_summary: Dict[str, Any], cumulative: Dict[str, Any]):
    if not report_path.exists() or report_path.stat().st_size == 0:
        report_path.write_text(
            "# DeepSeek 刀片缺陷识别累计验证结果\n\n"
            "本文件按运行次数追加保存，不会覆盖历史测试记录。\n",
            encoding="utf-8",
        )
    with report_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## 运行 {run_summary['run_id']}\n\n")
        handle.write(f"- 运行时间：{run_summary['run_started_at']}\n")
        handle.write(f"- 本次图片数：{run_summary['total_images']}\n")
        handle.write(f"- 本次成功请求：{run_summary['successful_requests']}\n")
        handle.write(f"- 本次失败请求：{run_summary['failed_requests']}\n")
        handle.write(
            f"- 本次候选分流：{json.dumps(run_summary['decision_counts'], ensure_ascii=False)}\n"
        )
        handle.write(f"- 本次基线冲突数：{run_summary['baseline_conflicts']}\n")
        handle.write("\n### 累计统计\n\n")
        handle.write(f"- 累计运行次数：{cumulative['total_runs']}\n")
        handle.write(f"- 累计图片数：{cumulative['total_images']}\n")
        handle.write(f"- 累计成功请求：{cumulative['successful_requests']}\n")
        handle.write(f"- 累计失败请求：{cumulative['failed_requests']}\n")
        handle.write(
            f"- 累计候选分流：{json.dumps(cumulative['decision_counts'], ensure_ascii=False)}\n"
        )
        handle.write(f"- 累计基线冲突数：{cumulative['baseline_conflicts']}\n")
        handle.write("\n详细逐图结果见 `deepseek_predictions.csv`，原始 JSON 见 `deepseek_raw.jsonl`。\n")


def run_batch(
    client,
    input_paths,
    output_dir: Path,
    labels_csv: Optional[Path] = None,
    baseline_predictions: Optional[Path] = None,
    detail: str = "original",
    max_tokens: int = 500,
):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    images = discover_images(input_paths)
    labels = _read_csv_index(labels_csv, label_mode=True)
    baseline = _read_csv_index(baseline_predictions, label_mode=False)
    started_at = datetime.now(timezone.utc)
    run_started_at = started_at.isoformat()
    run_id = _new_run_id(started_at)
    rows = []
    raw_records = []
    errors = 0

    for image_path in images:
        image_key = str(image_path.resolve()).lower()
        baseline_value = _first_not_none(
            baseline.get(image_key),
            baseline.get(image_path.name.lower()),
            baseline.get(image_path.stem.lower()),
        )
        baseline_label = _baseline_label(baseline_value)
        model_name = getattr(client, "model", "")
        response_id = ""
        elapsed_seconds = ""
        try:
            result = client.analyze_image(
                image_path,
                detail=detail,
                max_tokens=max_tokens,
            )
            parsed = result["parsed"]
            decision, predicted_label, conflict = _candidate_decision(
                parsed, baseline_label
            )
            model_name = result.get("model", model_name)
            response_id = result.get("response_id", "")
            elapsed_seconds = result.get("elapsed_seconds", "")
            raw_records.append(
                {
                    "run_id": run_id,
                    "run_started_at": run_started_at,
                    "image_path": str(image_path),
                    **result,
                }
            )
            error_text = ""
        except Exception as error:
            errors += 1
            parsed = {
                "has_defect": "uncertain",
                "image_quality": "unclear",
                "defects": [],
                "certainty": "low",
            }
            decision, predicted_label, conflict = (
                "manual_review_candidate",
                None,
                False,
            )
            error_text = _safe_error_text(error)
            raw_records.append(
                {
                    "run_id": run_id,
                    "run_started_at": run_started_at,
                    "image_path": str(image_path),
                    "error": error_text,
                }
            )

        truth = _first_not_none(
            labels.get(image_key),
            labels.get(image_path.name.lower()),
            labels.get(image_path.stem.lower()),
        )
        rows.append(
            {
                "image_path": str(image_path),
                "has_defect": parsed["has_defect"],
                "image_quality": parsed["image_quality"],
                "certainty": parsed["certainty"],
                "defect_count": len(parsed["defects"]),
                "defects_json": json.dumps(parsed["defects"], ensure_ascii=False),
                "decision_candidate": decision,
                "baseline_predicted_class": (
                    baseline_value if baseline_value is not None else ""
                ),
                "baseline_conflict": str(bool(conflict)).lower(),
                "error": error_text,
                "run_id": run_id,
                "run_started_at": run_started_at,
                "model": model_name,
                "response_id": response_id,
                "elapsed_seconds": elapsed_seconds,
                "ground_truth_label": truth if truth is not None else "",
            }
        )

    prediction_path = output_dir / "deepseek_predictions.csv"
    _append_prediction_rows(prediction_path, rows)
    with (output_dir / "deepseek_raw.jsonl").open("a", encoding="utf-8") as handle:
        for record in raw_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    all_rows = _read_prediction_rows(prediction_path)
    current_decisions = dict(Counter(row["decision_candidate"] for row in rows))
    cumulative_decisions = dict(Counter(row["decision_candidate"] for row in all_rows))
    current_summary = {
        "run_id": run_id,
        "run_started_at": run_started_at,
        "total_images": len(images),
        "successful_requests": len(images) - errors,
        "failed_requests": errors,
        "decision_counts": current_decisions,
        "deepseek_labeled_metrics": _metrics_from_rows(rows, "has_defect"),
        "baseline_labeled_metrics": _metrics_from_rows(
            rows, "baseline_predicted_class"
        ),
        "baseline_conflicts": sum(
            row["baseline_conflict"] == "true" for row in rows
        ),
    }

    summary_path = output_dir / "summary.json"
    old_summary = {}
    if summary_path.is_file():
        try:
            old_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old_summary = {}
    runs = list(old_summary.get("runs", []))
    runs.append(current_summary)
    cumulative_summary = {
        "schema_version": 2,
        "total_runs": len(runs),
        "total_images": len(all_rows),
        "successful_requests": sum(not row.get("error") for row in all_rows),
        "failed_requests": sum(bool(row.get("error")) for row in all_rows),
        "decision_counts": cumulative_decisions,
        "deepseek_labeled_metrics": _metrics_from_rows(all_rows, "has_defect"),
        "baseline_labeled_metrics": _metrics_from_rows(
            all_rows, "baseline_predicted_class"
        ),
        "baseline_conflicts": sum(
            row.get("baseline_conflict") == "true" for row in all_rows
        ),
        "latest_run": current_summary,
        "runs": runs,
        "note": "这是验证候选结果，不是经过质检真值校准的生产放行结论。",
    }
    summary_path.write_text(
        json.dumps(cumulative_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _append_report(output_dir / "REPORT.md", current_summary, cumulative_summary)
    return cumulative_summary
