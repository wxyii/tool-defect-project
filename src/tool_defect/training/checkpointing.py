"""Classification-priority validation metrics for model checkpointing."""

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


class ParentClassificationMetricsCallback(tf.keras.callbacks.Callback):
    """Compute parent-level classification metrics before checkpointing."""

    def __init__(self, validation_data, validation_rows, batch_size=32):
        super().__init__()
        self.validation_data = validation_data
        self.parent_ids = [parent_id_from_row(row) for row in validation_rows]
        self.labels = [int(row["label"]) for row in validation_rows]
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
