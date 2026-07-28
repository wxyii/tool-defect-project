"""Load the supplied Keras architecture and weight pair."""

from pathlib import Path


def load_saved_model(model_dir, weights_name="weights.h5"):
    # Register serializable project layers before deserializing source models.
    from tool_defect.models import cbam as _cbam  # noqa: F401
    from keras.src.saving import serialization_lib
    from tensorflow.keras.models import model_from_json

    # Legacy supplied JSON files contain trusted Lambda layers, while newly
    # generated models use the registered CBAM layers above.
    serialization_lib.enable_unsafe_deserialization()

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
