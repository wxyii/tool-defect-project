"""Image and mask preprocessing shared by training and inference."""

from pathlib import Path

import cv2
import numpy as np


def _read_grayscale(path):
    path = Path(path)
    try:
        encoded = np.fromfile(path, dtype=np.uint8)
    except OSError as error:
        raise ValueError(f"unable to read image: {path}") from error
    image = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"unable to read image: {path}")
    return image


def load_image(image_path, image_size=256):
    grayscale = _read_grayscale(image_path)
    resized = cv2.resize(
        grayscale,
        (image_size, image_size),
        interpolation=cv2.INTER_AREA,
    )
    rgb = cv2.cvtColor(resized, cv2.COLOR_GRAY2RGB)
    return rgb.astype(np.float32) / 255.0


def load_image_batch(image_path, image_size=256):
    return np.expand_dims(load_image(image_path, image_size), axis=0)


def load_mask(mask_path, image_size=256):
    grayscale = _read_grayscale(mask_path)
    resized = cv2.resize(
        grayscale,
        (image_size, image_size),
        interpolation=cv2.INTER_NEAREST,
    )
    binary = (resized > 127).astype(np.int32)
    return np.eye(2, dtype=np.float32)[binary]
