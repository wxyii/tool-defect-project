"""Final classification training architecture retained from the supplied code."""

from tensorflow.keras import regularizers
from tensorflow.keras.applications import Xception
from tensorflow.keras.layers import (
    BatchNormalization,
    Concatenate,
    Conv2D,
    Dense,
    Dropout,
    Flatten,
    GlobalAveragePooling2D,
    MaxPooling2D,
)
from tensorflow.keras.models import Model

from tool_defect.models.cbam import cbam_block


def build_classifier(input_shape=(256, 256, 3), backbone_weights="imagenet"):
    backbone = Xception(
        input_shape=input_shape,
        weights=backbone_weights,
        include_top=False,
    )
    for layer in backbone.layers[:-10]:
        layer.trainable = False

    features = [
        backbone.get_layer(name).output
        for name in (
            "block1_conv1",
            "block4_sepconv1",
            "block7_sepconv1",
            "block10_sepconv1",
        )
    ]
    features.append(backbone.output)
    attended = [cbam_block(feature) for feature in features]
    aligned = [
        MaxPooling2D(pool_size=size, strides=size, padding="same")(
            Conv2D(256, 1, activation="relu", padding="same")(feature)
        )
        for feature, size in zip(attended, (16, 4, 2, 2, 1))
    ]
    x = Concatenate(axis=3)(aligned)
    x = Conv2D(256, 1, activation="relu", padding="same")(x)
    x = BatchNormalization()(x)
    x = GlobalAveragePooling2D()(x)
    x = Dropout(0.4)(x)
    x = Flatten()(x)
    x = Dense(256, activation="relu", kernel_regularizer=regularizers.l2(0.01))(x)
    x = Dense(128, activation="relu", kernel_regularizer=regularizers.l2(0.01))(x)
    output = Dense(2, activation="softmax", name="cla_out")(x)
    return Model(backbone.input, output, name="xception_cbam_classifier")
