"""Synchronized image/mask augmentation for the multitask model."""

import numpy as np
from tensorflow.keras.utils import Sequence


class CustomDataGenerator(Sequence):
    def __init__(
        self,
        images,
        classification_targets,
        segmentation_targets,
        batch_size=2,
        shuffle=True,
        augmentations=None,
        seed=1,
    ):
        self.images = images
        self.classification_targets = classification_targets
        self.segmentation_targets = segmentation_targets
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.augmentations = augmentations
        self.randomizer = np.random.default_rng(seed)
        self.indexes = np.arange(len(images))
        self.on_epoch_end()

    def __len__(self):
        return int(np.ceil(len(self.images) / self.batch_size))

    def __getitem__(self, index):
        indexes = self.indexes[
            index * self.batch_size : (index + 1) * self.batch_size
        ]
        images = self.images[indexes]
        classification = self.classification_targets[indexes]
        segmentation = self.segmentation_targets[indexes]
        if self.augmentations is not None:
            transform_seed = int(self.randomizer.integers(0, 2**31 - 1))
            images = next(
                self.augmentations.flow(
                    images,
                    batch_size=len(images),
                    shuffle=False,
                    seed=transform_seed,
                )
            )
            segmentation = next(
                self.augmentations.flow(
                    segmentation,
                    batch_size=len(segmentation),
                    shuffle=False,
                    seed=transform_seed,
                )
            )
            segmentation = np.eye(2, dtype=np.float32)[
                np.argmax(segmentation, axis=-1)
            ]
        return images, {
            "cla_out": classification,
            "seg_out": segmentation,
        }

    def on_epoch_end(self):
        if self.shuffle:
            self.randomizer.shuffle(self.indexes)
