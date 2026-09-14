"""Classification-priority validation metrics for model checkpointing."""

import csv
from collections import OrderedDict
from pathlib import Path

import numpy as np
import tensorflow as tf


def parent_id_from_row(row):
    """Return one stable ID for a full image and all of its patches."""
    explicit = row.get("parent_sample_id")
    if explicit:
        return str(explicit)
    sample_id = str(row["sample_id"])
    if "__patch_" in sample_id:
        # 子图的类别目录可能因掩码是否含缺陷而不同；父图身份必须取
        # 文件名中的稳定部分，不能把 qualified/ 和 unqualified/ 当成父图。
        return Path(sample_id).name.split("__patch_", 1)[0]
    return sample_id


def parent_labels_for_rows(rows, provenance_path=None):
    """Return labels for parent-level validation metrics in row order.

    Patch training keeps local child labels for its classification loss.  When
    the provenance file is available, checkpoint validation must instead use
    the parent label so mixed child labels do not make one parent invalid.
    Full-image datasets keep the manifest-label fallback for compatibility.
    """
    rows = list(rows)
    fallback = [int(row["label"]) for row in rows]
    if provenance_path is None:
        return fallback

    provenance_path = Path(provenance_path)
    if not provenance_path.is_file():
        return fallback

    provenance_by_sample = {}
    with provenance_path.open(newline="", encoding="utf-8-sig") as handle:
        for metadata in csv.DictReader(handle):
            sample_id = metadata.get("sample_id")
            if not sample_id:
                raise RuntimeError(
                    f"provenance缺少sample_id：{provenance_path}"
                )
            if sample_id in provenance_by_sample:
                raise RuntimeError(f"provenance存在重复sample_id：{sample_id}")
            provenance_by_sample[sample_id] = metadata

    labels = []
    parent_labels = {}
    for row in rows:
        sample_id = str(row["sample_id"])
        metadata = provenance_by_sample.get(sample_id)
        if metadata is None:
            raise RuntimeError(
                f"验证集样本未在provenance中找到：{sample_id}"
            )
        raw_parent_label = metadata.get("parent_label")
        if raw_parent_label in (None, ""):
            raise RuntimeError(f"provenance缺少parent_label：{sample_id}")
        parent_label = int(raw_parent_label)
        if parent_label not in (0, 1):
            raise RuntimeError(
                f"provenance的parent_label不是0/1：{sample_id}={raw_parent_label}"
            )
        parent_id = metadata.get("parent_sample_id") or parent_id_from_row(row)
        previous = parent_labels.get(parent_id)
        if previous is not None and previous != parent_label:
            raise RuntimeError(f"同一父样本存在不一致parent_label：{parent_id}")
        parent_labels[parent_id] = parent_label
        labels.append(parent_label)
    return labels


class ParentClassificationMetricsCallback(tf.keras.callbacks.Callback):
    """Compute parent-level classification metrics before checkpointing."""

    def __init__(
        self,
        validation_data,
        validation_rows,
        batch_size=32,
        validation_parent_labels=None,
    ):
        super().__init__()
        self.validation_data = validation_data
        self.parent_ids = [parent_id_from_row(row) for row in validation_rows]
        self.labels = (
            [int(label) for label in validation_parent_labels]
            if validation_parent_labels is not None
            else [int(row["label"]) for row in validation_rows]
        )
        if len(self.labels) != len(self.parent_ids):
            raise ValueError("父图验证标签数量与验证集清单行数不一致")
        self.batch_size = int(batch_size)

    def _classification_output(self, predictions):
        if isinstance(predictions, dict):
            return predictions["cla_out"]
        if isinstance(predictions, (list, tuple)):
            index = self.model.output_names.index("cla_out")
            return predictions[index]
        return predictions

    def on_epoch_end(self, epoch, logs=None):
        del epoch
        logs = logs if logs is not None else {}
        predictions = self.model.predict(
            self.validation_data,
            batch_size=self.batch_size,
            verbose=0,
        )
        probabilities = np.asarray(
            self._classification_output(predictions), dtype=np.float32
        )
        if len(probabilities) != len(self.parent_ids):
            raise RuntimeError("验证集预测数量与清单行数不一致")

        parent_probabilities = OrderedDict()
        parent_labels = {}
        for parent_id, label, probability in zip(
            self.parent_ids, self.labels, probabilities
        ):
            if parent_id in parent_labels and parent_labels[parent_id] != label:
                raise RuntimeError(f"同一父样本存在不一致分类标签：{parent_id}")
            parent_labels[parent_id] = label
            parent_probabilities[parent_id] = max(
                float(probability[1]),
                parent_probabilities.get(parent_id, 0.0),
            )

        truth = np.asarray(list(parent_labels.values()), dtype=np.int32)
        scores = np.asarray(
            [parent_probabilities[parent_id] for parent_id in parent_labels],
            dtype=np.float32,
        )
        predicted = scores >= 0.5
        actual = truth == 1
        true_positive = int(np.sum(predicted & actual))
        actual_positive = int(np.sum(actual))
        predicted_positive = int(np.sum(predicted))
        recall = true_positive / actual_positive if actual_positive else 0.0
        precision = (
            true_positive / predicted_positive if predicted_positive else 0.0
        )
        accuracy = float(np.mean(predicted == actual)) if len(actual) else 0.0
        f2 = (
            5.0 * precision * recall / (4.0 * precision + recall)
            if precision + recall
            else 0.0
        )
        logs.update(
            {
                "val_parent_accuracy": accuracy,
                "val_parent_unqualified_recall": recall,
                "val_parent_unqualified_precision": precision,
                "val_parent_unqualified_f2": f2,
            }
        )
