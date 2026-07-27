"""Memory-efficient balanced batches with synchronized mask augmentation."""

import math
from pathlib import Path

import numpy as np
import tensorflow as tf

from tool_defect.data.datasets import load_manifest_rows
from tool_defect.data.preprocess import load_image, load_mask


class BalancedMultitaskSequence(tf.keras.utils.Sequence):
    """Load multitask samples on demand with deterministic class balancing."""

    def __init__(
        self,
        manifest_path,
        data_root,
        split,
        image_size=256,
        batch_size=2,
        seed=1,
        augment=False,
        photometric=True,
        balanced=True,
    ):
        self.manifest_path = Path(manifest_path)
        self.data_root = Path(data_root)
        self.split = split
        self.image_size = int(image_size)
        self.batch_size = int(batch_size)
        self.seed = int(seed)
        self.augment = bool(augment)
        self.photometric = bool(photometric)
        self.balanced = bool(balanced)
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")
        if self.balanced and self.batch_size % 2:
            raise ValueError("balanced batch_size must be even")

        self.rows = load_manifest_rows(self.manifest_path, split)
        if not self.rows:
            raise ValueError(f"manifest contains no rows for split '{split}'")
        self.by_label = {
            label: [row for row in self.rows if int(row["label"]) == label]
            for label in (0, 1)
        }
        if self.balanced and any(not rows for rows in self.by_label.values()):
            raise ValueError("balanced sequence requires both classes")
        self.epoch = 0
        self._refresh_orders()

    def _refresh_orders(self):
        randomizer = np.random.default_rng(self.seed + self.epoch * 100003)
        self.order = np.arange(len(self.rows))
        if self.augment:
            randomizer.shuffle(self.order)
        self.class_orders = {}
        for label, rows in self.by_label.items():
            order = np.arange(len(rows))
            if self.augment:
                randomizer.shuffle(order)
            self.class_orders[label] = order

    def __len__(self):
        if not self.balanced:
            return math.ceil(len(self.rows) / self.batch_size)
        per_class = self.batch_size // 2
        return math.ceil(
            max(len(self.by_label[0]), len(self.by_label[1])) / per_class
        )

    def _rows_for_batch(self, index):
        if index < 0 or index >= len(self):
            raise IndexError(index)
        if not self.balanced:
            start = index * self.batch_size
            indexes = self.order[start : start + self.batch_size]
            return [self.rows[item] for item in indexes]

        per_class = self.batch_size // 2
        selected = []
        for label in (0, 1):
            order = self.class_orders[label]
            for offset in range(per_class):
                position = (index * per_class + offset) % len(order)
                selected.append(self.by_label[label][int(order[position])])
        randomizer = np.random.default_rng(
            self.seed + self.epoch * 100003 + index * 97 + 17
        )
        randomizer.shuffle(selected)
        return selected

    def _augment_pair(self, image, mask, index, position):
        if not self.augment:
            return image, mask
        randomizer = np.random.default_rng(
            self.seed
            + self.epoch * 100003
            + index * 101
            + position * 1009
        )
        rotations = int(randomizer.integers(0, 4))
        image = np.rot90(image, rotations, axes=(0, 1))
        mask = np.rot90(mask, rotations, axes=(0, 1))
        if randomizer.random() < 0.5:
            image = np.flip(image, axis=1)
            mask = np.flip(mask, axis=1)
        if randomizer.random() < 0.5:
            image = np.flip(image, axis=0)
            mask = np.flip(mask, axis=0)
        if self.photometric:
            contrast = float(randomizer.uniform(0.9, 1.1))
            brightness = float(randomizer.uniform(-0.05, 0.05))
            image = np.clip((image - 0.5) * contrast + 0.5 + brightness, 0, 1)
        return (
            np.ascontiguousarray(image, dtype=np.float32),
            np.ascontiguousarray(mask, dtype=np.float32),
        )

    def __getitem__(self, index):
        rows = self._rows_for_batch(index)
        images = []
        masks = []
        labels = []
        for position, row in enumerate(rows):
            image = load_image(
                self.data_root / row["image_path"], self.image_size
            )
            mask = load_mask(self.data_root / row["mask_path"], self.image_size)
            image, mask = self._augment_pair(image, mask, index, position)
            images.append(image)
            masks.append(mask)
            labels.append(int(row["label"]))
        label_targets = np.eye(2, dtype=np.float32)[
            np.asarray(labels, dtype=np.int32)
        ]
        return np.stack(images), {
            "cla_out": label_targets,
            "seg_out": np.stack(masks),
        }

    def on_epoch_end(self):
        self.epoch += 1
        self._refresh_orders()
