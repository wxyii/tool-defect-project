"""Orchestrate, fairly evaluate, and visualize the five multitask models."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys


DEFAULT_GPUS = (0, 1, 2, 3, 5)
DEFAULT_SPLIT = "test"


@dataclass(frozen=True)
class DatasetSpec:
    """One dataset, its config, and its dedicated model artifact directory."""

    dataset_id: str
    name: str
    config_path: str
    artifact_path: str
    chunked: bool
    parent_data_path: str = ""


DATASET_SPECS = (
    DatasetSpec(
        "raw",
        "原始未预处理",
        "configs/default.json",
        "artifacts/multitask",
        False,
    ),
    DatasetSpec(
        "adaptive_annular",
        "自适应环形",
        "configs/multitask_adaptive_annular.json",
        "artifacts/multitask_suite/adaptive_annular",
        False,
    ),
    DatasetSpec(
        "boundary_normalized",
        "边界归一化",
        "configs/multitask_boundary_normalized.json",
        "artifacts/multitask_suite/boundary_normalized",
        False,
    ),
    DatasetSpec(
        "adaptive_annular_8patch",
        "自适应环形分块",
        "configs/multitask_adaptive_annular_8patch.json",
        "artifacts/multitask_suite/adaptive_annular_8patch",
        True,
        "data/processed/adaptive_annular",
    ),
    DatasetSpec(
        "boundary_normalized_8patch",
        "边界归一化分块",
        "configs/multitask_boundary_normalized_8patch.json",
        "artifacts/multitask_suite/boundary_normalized_8patch",
        True,
        "data/processed/boundary_normalized",
    ),
)

_MANIFEST_FIELDS = {
    "sample_id",
    "image_path",
    "mask_path",
    "label",
    "label_name",
    "split",
}
_PROVENANCE_FIELDS = {
    "sample_id",
    "parent_sample_id",
    "parent_image_path",
    "parent_mask_path",
    "parent_label",
    "parent_label_name",
    "split",
    "patch_index",
    "start_angle_degrees",
    "source_height",
    "source_width",
    "output_height",
    "output_width",
}


def parse_gpu_ids(value):
    """Parse a comma-separated GPU list and reject duplicate assignments."""

    if isinstance(value, str):
        tokens = [token.strip() for token in value.split(",")]
    else:
        tokens = list(value)
    if not tokens or any(token == "" for token in tokens):
        raise ValueError("显卡列表不能为空，格式应为：0,1,2")
    gpu_ids = []
    for token in tokens:
        try:
            gpu_id = int(token)
        except (TypeError, ValueError) as error:
            raise ValueError(f"无效的显卡编号：{token}") from error
        if gpu_id < 0:
            raise ValueError(f"显卡编号不能为负数：{gpu_id}")
        if gpu_id in gpu_ids:
            raise ValueError(f"显卡编号重复：{gpu_id}")
        gpu_ids.append(gpu_id)
    return tuple(gpu_ids)


def _absolute_path(project_root, value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def _read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _safe_data_path(data_root, relative_path, description):
    relative = Path(relative_path)
    if not relative_path or relative.is_absolute() or relative.drive:
        raise ValueError(f"{description} 必须是数据根目录相对路径：{relative_path}")
    candidate = (Path(data_root) / relative).resolve()
    try:
        candidate.relative_to(Path(data_root).resolve())
    except ValueError as error:
        raise ValueError(f"{description} 超出数据根目录：{relative_path}") from error
    return candidate


def _load_spec_paths(project_root, spec):
    project_root = Path(project_root).resolve()
    config_path = project_root / spec.config_path
    if not config_path.is_file():
        return {
            "project_root": project_root,
            "config": config_path,
            "config_values": {},
            "data_root": project_root,
            "parent_data_root": project_root,
            "manifest": project_root / "missing-manifest.csv",
            "artifact_dir": (project_root / spec.artifact_path).resolve(),
            "provenance": None,
        }
    with config_path.open(encoding="utf-8") as handle:
        config = json.load(handle)
    paths = config.get("paths", {})
    data_root = _absolute_path(project_root, paths["data"])
    manifest = _absolute_path(project_root, paths["manifest"])
    artifact_dir = (project_root / spec.artifact_path).resolve()
    parent_data_root = (
        _absolute_path(project_root, spec.parent_data_path)
        if spec.parent_data_path
        else data_root
    )
    provenance = data_root / "manifests" / "provenance.csv"
    return {
        "project_root": project_root,
        "config": config_path,
        "config_values": config,
        "data_root": data_root,
        "manifest": manifest,
        "artifact_dir": artifact_dir,
        "parent_data_root": parent_data_root,
        "provenance": provenance if spec.chunked else None,
    }


def artifact_status(artifact_dir):
    """Return the completeness of one loadable JSON/H5 model artifact."""

    artifact_dir = Path(artifact_dir).resolve()
    required = (artifact_dir / "model.json", artifact_dir / "weights.h5")
    missing = [str(path) for path in required if not path.is_file()]
    return {
        "directory": str(artifact_dir),
        "complete": not missing,
        "missing": missing,
    }


def _validate_data_inputs(spec, paths, split):
    errors = []
    config = paths["config"]
    if not config.is_file():
        errors.append(f"配置不存在：{config}")
    if not paths["data_root"].is_dir():
        errors.append(f"数据目录不存在：{paths['data_root']}")
    if spec.chunked and not paths["parent_data_root"].is_dir():
        errors.append(f"分块对应的父数据目录不存在：{paths['parent_data_root']}")
    if not paths["manifest"].is_file():
        errors.append(f"数据清单不存在：{paths['manifest']}")
        return errors
    try:
        rows = _read_csv(paths["manifest"])
    except (OSError, csv.Error, UnicodeError) as error:
        return [f"无法读取数据清单：{paths['manifest']}（{error}）"]
    if not rows:
        errors.append(f"数据清单为空：{paths['manifest']}")
        return errors
    missing_fields = _MANIFEST_FIELDS.difference(rows[0])
    if missing_fields:
        errors.append(f"数据清单缺少字段：{sorted(missing_fields)}")
    for row in rows:
        if row.get("split") != split:
            continue
        for field in ("image_path", "mask_path"):
            try:
                path = _safe_data_path(
                    paths["data_root"],
                    row.get(field, ""),
                    f"{row.get('sample_id', '<unknown>')} 的 {field}",
                )
            except ValueError as error:
                errors.append(str(error))
                continue
            if not path.is_file():
                errors.append(f"文件不存在：{path}")
    if spec.chunked:
        provenance = paths["provenance"]
        if not provenance.is_file():
            errors.append(f"分块溯源清单不存在：{provenance}")
        else:
            try:
                provenance_rows = _read_csv(provenance)
                missing_provenance = _PROVENANCE_FIELDS.difference(
                    provenance_rows[0] if provenance_rows else {}
                )
                if missing_provenance:
                    errors.append(
                        f"分块溯源清单缺少字段：{sorted(missing_provenance)}"
                    )
                manifest_ids = {
                    row["sample_id"]
                    for row in rows
                    if row.get("split") == split
                }
                provenance_ids = {
                    row["sample_id"]
                    for row in provenance_rows
                    if row.get("split") == split
                }
                if manifest_ids != provenance_ids:
                    errors.append(
                        "分块清单与溯源清单的测试子图不一致："
                        f"清单缺少 {sorted(provenance_ids - manifest_ids)[:3]}，"
                        f"溯源缺少 {sorted(manifest_ids - provenance_ids)[:3]}"
                    )
                for row in provenance_rows:
                    if row.get("split") != split:
                        continue
                    for field in ("parent_image_path", "parent_mask_path"):
                        try:
                            path = _safe_data_path(
                                paths["parent_data_root"],
                                row.get(field, ""),
                                f"{row.get('parent_sample_id', '<unknown>')} 的 {field}",
                            )
                        except ValueError as error:
                            errors.append(str(error))
                            continue
                        if not path.is_file():
                            errors.append(f"父图文件不存在：{path}")
            except (OSError, csv.Error, UnicodeError) as error:
                errors.append(f"无法读取分块溯源清单：{error}")
    return errors


def build_run_plan(
    project_root,
    output_root,
    gpus,
    split=DEFAULT_SPLIT,
    max_workers=None,
    python_executable=None,
):
    """Build a serializable preflight plan without importing TensorFlow."""

    project_root = Path(project_root).resolve()
    output_root = Path(output_root).resolve()
    gpu_ids = parse_gpu_ids(gpus)
    if max_workers is None:
        worker_count = len(gpu_ids)
    else:
        worker_count = int(max_workers)
        if worker_count < 1:
            raise ValueError("max_workers 必须为正数")
        worker_count = min(worker_count, len(gpu_ids))
    python_executable = Path(python_executable or sys.executable)
    entries = []
    errors = []
    for spec in DATASET_SPECS:
        paths = _load_spec_paths(project_root, spec)
        data_errors = _validate_data_inputs(spec, paths, split)
        status = artifact_status(paths["artifact_dir"])
        entry = {
            "dataset_id": spec.dataset_id,
            "name": spec.name,
            "chunked": spec.chunked,
            "config": str(paths["config"]),
            "data_root": str(paths["data_root"]),
            "parent_data_root": str(paths["parent_data_root"]),
            "manifest": str(paths["manifest"]),
            "provenance": (
                str(paths["provenance"]) if paths["provenance"] else ""
            ),
            "artifact": status,
            "train_required": not status["complete"],
            "train_command": [
                str(python_executable),
                "-m",
                "tool_defect.cli",
                "train",
                "--task",
                "multitask",
                "--config",
                str(paths["config"]),
                "--output",
                str(paths["artifact_dir"]),
            ],
            "output": str(output_root / spec.dataset_id),
            "preflight_errors": data_errors,
        }
        entries.append(entry)
        errors.extend(f"{spec.dataset_id}：{error}" for error in data_errors)

    pending = [entry for entry in entries if entry["train_required"]]
    active_gpus = gpu_ids[:worker_count]
    for index, entry in enumerate(pending):
        entry["planned_gpu"] = active_gpus[index % len(active_gpus)]
    return {
        "project_root": str(project_root),
        "output_root": str(output_root),
        "split": split,
        "gpus": list(gpu_ids),
        "max_workers": worker_count,
        "datasets": entries,
        "preflight_errors": errors,
    }


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _tail(path, max_chars=3000):
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return content[-max_chars:]


def _train_one(entry, gpu_id, project_root, log_dir, python_executable):
    log_path = Path(log_dir) / f"{entry['dataset_id']}.train.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    source_path = str(Path(project_root) / "src")
    old_python_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        [source_path] + ([old_python_path] if old_python_path else [])
    )
    command = [str(python_executable), *entry["train_command"][1:]]
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(f"显卡：{gpu_id}\n命令：{' '.join(command)}\n\n")
        try:
            completed = subprocess.run(
                command,
                cwd=str(project_root),
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                check=False,
            )
        except OSError as error:
            raise RuntimeError(
                f"{entry['dataset_id']} 训练进程无法启动：{error}"
            ) from error
    if completed.returncode != 0:
        raise RuntimeError(
            f"{entry['dataset_id']} 训练失败，退出码 {completed.returncode}，"
            f"日志：{log_path}\n{_tail(log_path)}"
        )
    status = artifact_status(entry["artifact"]["directory"])
    if not status["complete"]:
        raise RuntimeError(
            f"{entry['dataset_id']} 训练完成但模型工件不完整：{status['missing']}"
        )
    return {
        "dataset_id": entry["dataset_id"],
        "status": "trained",
        "gpu": gpu_id,
        "log": str(log_path),
    }


def _train_missing(plan, project_root, python_executable):
    pending = [entry for entry in plan["datasets"] if entry["train_required"]]
    if not pending:
        return []
    gpu_ids = plan["gpus"]
    if not gpu_ids:
        raise ValueError("存在缺失模型，但没有可用显卡")
    max_workers = min(plan["max_workers"], len(gpu_ids), len(pending))
    log_dir = Path(plan["output_root"]) / "logs"
    results = []
    for start in range(0, len(pending), max_workers):
        batch = pending[start : start + max_workers]
        assignments = list(zip(batch, gpu_ids[: len(batch)]))
        with ThreadPoolExecutor(max_workers=len(assignments)) as executor:
            futures = [
                executor.submit(
                    _train_one,
                    entry,
                    gpu_id,
                    project_root,
                    log_dir,
                    python_executable,
                )
                for entry, gpu_id in assignments
            ]
            batch_errors = []
            for future in futures:
                try:
                    results.append(future.result())
                except Exception as error:
                    batch_errors.append(str(error))
            if batch_errors:
                raise RuntimeError("并行训练批次失败：\n" + "\n".join(batch_errors))
    return results


def _read_binary_mask(path):
    import cv2
    import numpy as np

    path = Path(path)
    encoded = np.fromfile(str(path), dtype=np.uint8)
    mask = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise ValueError(f"无法读取掩膜：{path}")
    return (mask > 127).astype(np.uint8)


def _one_hot_mask(mask):
    import numpy as np

    mask = (mask > 0).astype(np.int32)
    return np.eye(2, dtype=np.float32)[mask]


def _named_predictions(model, predictions):
    if not isinstance(predictions, (list, tuple)):
        predictions = [predictions]
    return dict(zip(model.output_names, predictions))


def _load_model_predictions(model_dir, images):
    import numpy as np
    import tensorflow as tf

    from tool_defect.data.preprocess import (
        apply_input_preprocessing,
        artifact_preprocessing_mode,
    )
    from tool_defect.models.loader import load_saved_model

    model = load_saved_model(model_dir)
    try:
        if "cla_out" not in model.output_names or "seg_out" not in model.output_names:
            raise ValueError(
                f"不是双任务模型，输出名称为：{model.output_names}"
            )
        preprocessing = artifact_preprocessing_mode(model_dir)
        predictions = model.predict(
            apply_input_preprocessing(images, preprocessing),
            verbose=0,
        )
        named = _named_predictions(model, predictions)
        return (
            np.asarray(named["cla_out"]),
            np.asarray(named["seg_out"]),
            int(model.input_shape[1]),
        )
    finally:
        del model
        tf.keras.backend.clear_session()


def _load_chunk_result(spec, paths, split):
    import cv2
    import numpy as np

    from tool_defect.data.datasets import load_dataset
    from tool_defect.data.circular_slice_dataset import annular_sector_mask

    images, labels, masks, rows = load_dataset(
        paths["manifest"],
        paths["data_root"],
        split,
        include_masks=True,
        return_rows=True,
    )
    class_probabilities, segmentation_probabilities, image_size = (
        _load_model_predictions(paths["artifact_dir"], images)
    )
    provenance_rows = _read_csv(paths["provenance"])
    provenance = {row["sample_id"]: row for row in provenance_rows}
    groups = OrderedDict()
    for index, row in enumerate(rows):
        if row["sample_id"] not in provenance:
            raise ValueError(f"找不到子图溯源信息：{row['sample_id']}")
        metadata = provenance[row["sample_id"]]
        parent_id = metadata["parent_sample_id"]
        groups.setdefault(parent_id, []).append((index, metadata))

    parent_ids = list(groups)
    parent_labels = []
    parent_classification = []
    parent_segmentation = []
    parent_masks = []
    parent_images = []
    for parent_id, children in groups.items():
        metadata_values = {item[1]["parent_label"] for item in children}
        if len(metadata_values) != 1:
            raise ValueError(f"父图标签不一致：{parent_id}")
        source_shapes = {
            (int(item[1]["source_height"]), int(item[1]["source_width"]))
            for item in children
        }
        if len(source_shapes) != 1:
            raise ValueError(f"父图尺寸不一致：{parent_id}")
        source_height, source_width = next(iter(source_shapes))
        first_metadata = children[0][1]
        parent_image = _safe_data_path(
            paths.get("parent_data_root", paths["data_root"]),
            first_metadata["parent_image_path"],
            f"{parent_id} 的父图像",
        )
        parent_mask_path = _safe_data_path(
            paths.get("parent_data_root", paths["data_root"]),
            first_metadata["parent_mask_path"],
            f"{parent_id} 的父掩膜",
        )
        parent_mask = _read_binary_mask(parent_mask_path)
        if parent_mask.shape != (source_height, source_width):
            raise ValueError(
                f"父图掩膜尺寸不一致：{parent_id}，"
                f"清单为 {(source_height, source_width)}，实际为 {parent_mask.shape}"
            )
        defect_probability = np.zeros((source_height, source_width), dtype=np.float32)
        unqualified_probability = 0.0
        for child_index, metadata in children:
            unqualified_probability = max(
                unqualified_probability,
                float(class_probabilities[child_index, 1]),
            )
            patch_probability = segmentation_probabilities[child_index, ..., 1]
            start_angle = float(metadata["start_angle_degrees"])
            if "center_x" in metadata:
                patch_probability = cv2.resize(
                    patch_probability,
                    (source_width, source_height),
                    interpolation=cv2.INTER_LINEAR,
                )
                window = float(metadata["end_angle_degrees"]) - start_angle
                sector = annular_sector_mask(
                    (source_height, source_width),
                    (float(metadata["center_x"]), float(metadata["center_y"])),
                    start_angle,
                    window,
                )
                patch_probability = np.where(sector, patch_probability, 0.0)
                defect_probability = np.maximum(
                    defect_probability, patch_probability
                )
            else:
                patch_height = int(metadata["output_height"])
                patch_width = int(metadata["output_width"])
                patch_probability = cv2.resize(
                    patch_probability,
                    (patch_width, patch_height),
                    interpolation=cv2.INTER_LINEAR,
                )
                if patch_height != source_height:
                    raise ValueError(
                        f"边界归一化子图高度与父图不一致：{parent_id}"
                    )
                start_column = round(source_width * start_angle / 360.0)
                columns = (
                    np.arange(start_column, start_column + patch_width)
                    % source_width
                ).astype(np.intp)
                defect_probability[:, columns] = np.maximum(
                    defect_probability[:, columns], patch_probability
                )
        parent_labels.append(int(next(iter(metadata_values))))
        parent_classification.append(
            [1.0 - unqualified_probability, unqualified_probability]
        )
        parent_segmentation.append(
            np.stack([1.0 - defect_probability, defect_probability], axis=-1)
        )
        parent_masks.append(_one_hot_mask(parent_mask))
        parent_images.append(parent_image)

    patch_metrics = _patch_metrics(
        labels, masks, class_probabilities, segmentation_probabilities
    )
    return {
        "parent_ids": parent_ids,
        "true_labels": np.asarray(parent_labels, dtype=np.int32),
        "class_probabilities": np.asarray(parent_classification, dtype=np.float32),
        "segmentation_probabilities": np.asarray(parent_segmentation, dtype=np.float32),
        "masks": np.asarray(parent_masks, dtype=np.float32),
        "parent_images": parent_images,
        "input_size": image_size,
        "patch_metrics": patch_metrics,
    }


def _patch_metrics(labels, masks, class_probabilities, segmentation_probabilities):
    import numpy as np

    from tool_defect.evaluation.metrics import (
        classification_metrics,
        segmentation_metrics,
    )

    classification, _ = classification_metrics(
        np.argmax(labels, axis=-1), class_probabilities
    )
    segmentation, _ = segmentation_metrics(masks, segmentation_probabilities)
    return {
        "samples": int(len(labels)),
        "classification_accuracy": classification["accuracy"],
        "classification": classification,
        "mean_iou": segmentation["mean_iou"],
        "segmentation": segmentation,
    }


def _load_dataset_result(spec, paths, split):
    import numpy as np

    if spec.chunked:
        return _load_chunk_result(spec, paths, split)
    from tool_defect.data.datasets import load_dataset

    images, labels, masks, rows = load_dataset(
        paths["manifest"],
        paths["data_root"],
        split,
        include_masks=True,
        return_rows=True,
    )
    class_probabilities, segmentation_probabilities, image_size = (
        _load_model_predictions(paths["artifact_dir"], images)
    )
    return {
        "parent_ids": [row["sample_id"] for row in rows],
        "true_labels": np.argmax(labels, axis=-1).astype(np.int32),
        "class_probabilities": class_probabilities,
        "segmentation_probabilities": segmentation_probabilities,
        "masks": masks,
        "parent_images": [
            _safe_data_path(
                paths["data_root"], row["image_path"], row["sample_id"]
            )
            for row in rows
        ],
        "input_size": image_size,
        "patch_metrics": None,
    }


def _reorder_result(result, parent_ids):
    import numpy as np

    indexes = {sample_id: index for index, sample_id in enumerate(result["parent_ids"])}
    if set(indexes) != set(parent_ids):
        raise ValueError("五个数据集的父图测试集不一致")
    order = [indexes[sample_id] for sample_id in parent_ids]
    return {
        **result,
        "parent_ids": list(parent_ids),
        "true_labels": result["true_labels"][order],
        "class_probabilities": result["class_probabilities"][order],
        "segmentation_probabilities": result["segmentation_probabilities"][order],
        "masks": result["masks"][order],
        "parent_images": [result["parent_images"][index] for index in order],
    }


def _write_png(path, image):
    import cv2

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(
        ".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 6]
    )
    if not success:
        raise OSError(f"无法写入 PNG：{path}")
    encoded.tofile(str(path))


def _safe_stem(sample_id):
    return "_".join(
        part for part in str(sample_id).replace("\\", "/").split("/") if part
    ).replace(" ", "_")


def _write_confusion_matrix(path, matrix, labels):
    with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["true/predicted", *labels])
        for label, row in zip(labels, matrix):
            writer.writerow([label, *[int(value) for value in row]])


def _write_model_outputs(spec, result, output_dir, split, threshold):
    import numpy as np

    from tool_defect.evaluation.metrics import (
        CLASS_NAMES,
        SEGMENT_NAMES,
        classification_metrics,
        segmentation_metrics,
    )
    from tool_defect.inference.visualize import overlay_defect_on_image

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    classification, classification_matrix = classification_metrics(
        result["true_labels"], result["class_probabilities"]
    )
    segmentation, segmentation_matrix = segmentation_metrics(
        result["masks"], result["segmentation_probabilities"], threshold=threshold
    )
    metrics = {
        "dataset_id": spec.dataset_id,
        "dataset_name": spec.name,
        "evaluation_level": "parent",
        "split": split,
        "samples": int(len(result["parent_ids"])),
        "classification_accuracy": classification["accuracy"],
        "classification": classification,
        "mean_iou": segmentation["mean_iou"],
        "segmentation": segmentation,
        "total_standardized_loss": (
            classification["cross_entropy_loss"]
            + segmentation["cross_entropy_loss"]
        ),
        "input_size": result["input_size"],
        "threshold": float(threshold),
        "aggregation": (
            "子图分类不合格概率取最大值；子图分割缺陷概率映射回父图后取最大值"
            if spec.chunked
            else "无分块聚合"
        ),
    }
    if result["patch_metrics"] is not None:
        metrics["patch_level_auxiliary_metrics"] = result["patch_metrics"]
    _write_json(output_dir / "metrics.json", metrics)
    _write_confusion_matrix(
        output_dir / "classification_confusion_matrix.csv",
        classification_matrix,
        CLASS_NAMES,
    )
    _write_confusion_matrix(
        output_dir / "segmentation_confusion_matrix.csv",
        segmentation_matrix,
        SEGMENT_NAMES,
    )

    mask_dir = output_dir / "masks"
    visualization_dir = output_dir / "visualizations"
    rows = []
    for index, (
        sample_id,
        true_label,
        class_probability,
        segmentation_probability,
        original_path,
    ) in enumerate(
        zip(
            result["parent_ids"],
            result["true_labels"],
            result["class_probabilities"],
            result["segmentation_probabilities"],
            result["parent_images"],
        )
    ):
        predicted_label = int(np.argmax(class_probability))
        defect_mask = (
            (segmentation_probability[..., 1] >= threshold).astype(np.uint8)
            * 255
        )
        stem = f"{index:04d}_{_safe_stem(sample_id)}"
        mask_path = mask_dir / f"{stem}.png"
        visualization_path = visualization_dir / f"{stem}_result.png"
        _write_png(mask_path, defect_mask)
        confidence = float(class_probability[predicted_label])
        overlay_defect_on_image(
            original_path=original_path,
            defect_mask=defect_mask,
            predicted_class=CLASS_NAMES[predicted_label],
            confidence=confidence,
            output_path=visualization_path,
        )
        rows.append(
            {
                "sample_id": sample_id,
                "image_path": str(original_path),
                "true_label": int(true_label),
                "true_class": CLASS_NAMES[int(true_label)],
                "predicted_label": predicted_label,
                "predicted_class": CLASS_NAMES[predicted_label],
                "qualified_probability": f"{float(class_probability[0]):.8f}",
                "unqualified_probability": f"{float(class_probability[1]):.8f}",
                "mask_path": (Path("masks") / f"{stem}.png").as_posix(),
                "visualization_path": (
                    Path("visualizations") / f"{stem}_result.png"
                ).as_posix(),
            }
        )
    with (output_dir / "predictions.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        fieldnames = list(rows[0]) if rows else ["sample_id"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return metrics


def _write_suite_report(output_root, metrics, split, parent_ids):
    fields = (
        "dataset_id",
        "dataset_name",
        "samples",
        "classification_accuracy",
        "unqualified_precision",
        "unqualified_recall",
        "unqualified_f1",
        "defect_iou",
        "defect_dice",
        "defect_precision",
        "defect_recall",
        "mean_iou",
    )
    with (output_root / "summary.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in metrics:
            classification = item["classification"]
            defect = item["segmentation"]["defect"]
            writer.writerow(
                {
                    "dataset_id": item["dataset_id"],
                    "dataset_name": item["dataset_name"],
                    "samples": item["samples"],
                    "classification_accuracy": item["classification_accuracy"],
                    "unqualified_precision": classification["unqualified"][
                        "precision"
                    ],
                    "unqualified_recall": classification["unqualified"][
                        "recall"
                    ],
                    "unqualified_f1": classification["unqualified"]["f1"],
                    "defect_iou": defect["iou"],
                    "defect_dice": defect["dice"],
                    "defect_precision": defect["precision"],
                    "defect_recall": defect["recall"],
                    "mean_iou": item["mean_iou"],
                }
            )
    lines = [
        "# 五类多任务模型父图级测试集对比",
        "",
        f"- 评估父图数量：{len(parent_ids)}",
        f"- 测试划分：{split}",
        "- 五个模型使用同一批父样本；分块模型先合并子图再计算主指标。",
        "",
        "| 模型 | 分类准确率 | 不合格F1 | 缺陷IoU | 缺陷Dice | 缺陷Precision | 缺陷Recall |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in metrics:
        classification = item["classification"]
        defect = item["segmentation"]["defect"]
        lines.append(
            f"| {item['dataset_name']} | {item['classification_accuracy']:.4f} "
            f"| {classification['unqualified']['f1']:.4f} "
            f"| {defect['iou']:.4f} | {defect['dice']:.4f} "
            f"| {defect['precision']:.4f} | {defect['recall']:.4f} |"
        )
    (output_root / "SUITE_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def evaluate_suite(project_root, plan, split=DEFAULT_SPLIT, threshold=0.5):
    """Evaluate all artifacts on one common parent test set and visualize them."""

    import numpy as np

    project_root = Path(project_root).resolve()
    results = []
    canonical_parent_ids = None
    for spec, entry in zip(DATASET_SPECS, plan["datasets"]):
        if not artifact_status(entry["artifact"]["directory"])["complete"]:
            raise FileNotFoundError(f"模型工件不完整：{entry['artifact']['directory']}")
        paths = _load_spec_paths(project_root, spec)
        result = _load_dataset_result(spec, paths, split)
        if canonical_parent_ids is None:
            canonical_parent_ids = list(result["parent_ids"])
            canonical_labels = result["true_labels"].copy()
        else:
            result = _reorder_result(result, canonical_parent_ids)
            if not np.array_equal(result["true_labels"], canonical_labels):
                raise ValueError(f"父图标签不一致：{spec.dataset_id}")
        if len(result["masks"]) != len(canonical_parent_ids):
            raise ValueError(f"父图数量不一致：{spec.dataset_id}")
        results.append((spec, entry, result))

    output_root = Path(plan["output_root"])
    metrics = []
    for spec, entry, result in results:
        model_metrics = _write_model_outputs(
            spec,
            result,
            output_root / spec.dataset_id,
            split,
            threshold,
        )
        metrics.append(model_metrics)
    summary = {
        "split": split,
        "samples": len(canonical_parent_ids or []),
        "parent_sample_ids": canonical_parent_ids,
        "same_parent_set": True,
        "fixed_segmentation_threshold": float(threshold),
        "models": metrics,
    }
    _write_json(output_root / "suite_metrics.json", summary)
    _write_suite_report(output_root, metrics, split, canonical_parent_ids or [])
    return summary


def run_suite(
    project_root,
    *,
    output_root,
    gpus=DEFAULT_GPUS,
    split=DEFAULT_SPLIT,
    simulate=False,
    python_executable=None,
    max_workers=None,
    threshold=0.5,
):
    """Preflight, train missing artifacts, evaluate, and visualize the suite."""

    if not 0.0 <= float(threshold) <= 1.0:
        raise ValueError("threshold 必须位于 [0, 1] 范围内")
    project_root = Path(project_root).resolve()
    output_root = Path(output_root).resolve()
    plan = build_run_plan(
        project_root,
        output_root,
        gpus,
        split=split,
        max_workers=max_workers,
        python_executable=python_executable,
    )
    if plan["preflight_errors"]:
        raise RuntimeError(
            "预检查失败：\n" + "\n".join(plan["preflight_errors"])
        )
    output_root.mkdir(parents=True, exist_ok=True)
    plan["simulate"] = bool(simulate)
    _write_json(output_root / "run_plan.json", plan)
    if simulate:
        return {"plan": plan, "training": [], "evaluation": None}

    python_executable = python_executable or sys.executable
    training = _train_missing(plan, project_root, python_executable)
    evaluation = evaluate_suite(
        project_root,
        plan,
        split=split,
        threshold=threshold,
    )
    return {"plan": plan, "training": training, "evaluation": evaluation}
