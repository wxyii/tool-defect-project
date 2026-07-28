"""Image and mask preprocessing shared by training and inference."""

import json
from pathlib import Path

import cv2
import numpy as np


ZERO_ONE = "zero_one"
XCEPTION = "xception"
_SUPPORTED_MODES = {ZERO_ONE, XCEPTION}


def apply_input_preprocessing(images, mode=ZERO_ONE):
    """Convert normalized [0, 1] images to an artifact's expected input range."""
    mode = str(mode)
    if mode not in _SUPPORTED_MODES:
        raise ValueError(f"unsupported input preprocessing mode: {mode}")
    images = np.asarray(images, dtype=np.float32)
    if mode == XCEPTION:
        return images * 2.0 - 1.0
    return images


def artifact_preprocessing_mode(model_dir):
    """Read artifact preprocessing metadata, defaulting legacy models to [0, 1]."""
    metadata_path = Path(model_dir) / "preprocessing.json"
    if not metadata_path.is_file():
        return ZERO_ONE
    with metadata_path.open(encoding="utf-8") as handle:
        metadata = json.load(handle)
    mode = metadata.get("mode")
    if mode not in _SUPPORTED_MODES:
        raise ValueError(
            f"invalid preprocessing mode in {metadata_path}: {mode!r}"
        )
    return mode


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
