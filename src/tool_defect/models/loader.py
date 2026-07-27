"""Load the supplied Keras architecture and weight pair."""

from pathlib import Path


def load_saved_model(model_dir, weights_name="weights.h5"):
    from tensorflow.keras.models import model_from_json

    model_dir = Path(model_dir)
    architecture_path = model_dir / "model.json"
    weights_path = model_dir / weights_name
    if not architecture_path.is_file():
        raise FileNotFoundError(f"model architecture not found: {architecture_path}")
    if not weights_path.is_file():
        raise FileNotFoundError(f"model weights not found: {weights_path}")

    architecture = architecture_path.read_text(encoding="utf-8")
    model = model_from_json(architecture)
    model.load_weights(weights_path)
    return model
