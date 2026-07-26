"""Standard attention gate used only by the retained AG+FPN reference."""

from tensorflow.keras.layers import (
    Activation,
    Add,
    BatchNormalization,
    Conv2D,
    Multiply,
    UpSampling2D,
)


def attention_gate(skip, gating):
    channels = int(skip.shape[-1])
    theta = Conv2D(channels, 1, padding="same", use_bias=True)(skip)
    phi = Conv2D(channels, 1, padding="same", use_bias=True)(gating)
    scale_height = int(theta.shape[1] // phi.shape[1])
    scale_width = int(theta.shape[2] // phi.shape[2])
    if (scale_height, scale_width) != (1, 1):
        phi = UpSampling2D(
            size=(scale_height, scale_width), interpolation="bilinear"
        )(phi)
    merged = Add()([theta, phi])
    merged = BatchNormalization()(merged)
    merged = Activation("relu")(merged)
    weights = Conv2D(1, 1, activation="sigmoid", padding="same")(merged)
    return Multiply()([skip, weights])
