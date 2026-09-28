"""批量调用 DeepSeek 并与现有算法结果做父图级对比。"""

import csv
import json
from collections import Counter
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
                    (candidate for candidate in path.rglob("*")
                     if candidate.is_file() and candidate.suffix.lower() in IMAGE_SUFFIXES),
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
            image_value = row.get("image_path") or row.get("path") or row.get("filename")
            if not image_value:
                continue
            value = row.get("label") or row.get("label_name") if label_mode else row.get("predicted_class")
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
    if str(row_value).strip().lower() in {"unqualified", "不合格", "bad", "1"}:
        return 1
    if str(row_value).strip().lower() in {"qualified", "合格", "good", "0"}:
        return 0
    return None


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
    rows = []
    raw_records = []
    metrics_pairs = []
    baseline_pairs = []
    errors = 0
    for index, image_path in enumerate(images):
        image_key = str(image_path.resolve()).lower()
        baseline_value = _first_not_none(
            baseline.get(image_key),
            baseline.get(image_path.name.lower()),
            baseline.get(image_path.stem.lower()),
        )
        baseline_label = _baseline_label(baseline_value)
        try:
            result = client.analyze_image(
                image_path,
                detail=detail,
                max_tokens=max_tokens,
            )
            parsed = result["parsed"]
            decision, predicted_label, conflict = _candidate_decision(parsed, baseline_label)
            raw_records.append({"image_path": str(image_path), **result})
            error_text = ""
        except Exception as error:
            errors += 1
            parsed = {
                "has_defect": "uncertain",
                "image_quality": "unclear",
                "defects": [],
                "certainty": "low",
            }
            decision, predicted_label, conflict = "manual_review_candidate", None, False
            error_text = f"{type(error).__name__}: {error}"
            raw_records.append({"image_path": str(image_path), "error": error_text})
        truth = _first_not_none(
            labels.get(image_key),
            labels.get(image_path.name.lower()),
            labels.get(image_path.stem.lower()),
        )
        if truth is not None and predicted_label is not None:
            metrics_pairs.append((predicted_label, truth))
        if truth is not None and baseline_label is not None:
            baseline_pairs.append((baseline_label, truth))
        rows.append(
            {
                "image_path": str(image_path),
                "has_defect": parsed["has_defect"],
                "image_quality": parsed["image_quality"],
                "certainty": parsed["certainty"],
                "defect_count": len(parsed["defects"]),
                "defects_json": json.dumps(parsed["defects"], ensure_ascii=False),
                "decision_candidate": decision,
                "baseline_predicted_class": baseline_value or "",
                "baseline_conflict": str(bool(conflict)).lower(),
                "error": error_text,
            }
        )

    prediction_path = output_dir / "deepseek_predictions.csv"
    with prediction_path.open("w", newline="", encoding="utf-8-sig") as handle:
        fieldnames = list(rows[0]) if rows else ["image_path"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with (output_dir / "deepseek_raw.jsonl").open("w", encoding="utf-8") as handle:
        for record in raw_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = {
        "total_images": len(images),
        "successful_requests": len(images) - errors,
        "failed_requests": errors,
        "decision_counts": dict(Counter(row["decision_candidate"] for row in rows)),
        "deepseek_labeled_metrics": _binary_metrics(metrics_pairs),
        "baseline_labeled_metrics": _binary_metrics(baseline_pairs),
        "baseline_conflicts": sum(row["baseline_conflict"] == "true" for row in rows),
        "note": "这是验证候选结果，不是经过质检真值校准的生产放行结论。",
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report_lines = [
        "# DeepSeek 刀片缺陷识别验证结果",
        "",
        f"- 图片数：{summary['total_images']}",
        f"- 成功请求：{summary['successful_requests']}",
        f"- 失败请求：{summary['failed_requests']}（失败必须进入人工复检）",
        f"- 候选分流：{json.dumps(summary['decision_counts'], ensure_ascii=False)}",
        f"- 与现有算法冲突数：{summary['baseline_conflicts']}",
        "",
        "详细逐图结果见 `deepseek_predictions.csv`，原始 JSON 见 `deepseek_raw.jsonl`。",
    ]
    (output_dir / "REPORT.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return summary
