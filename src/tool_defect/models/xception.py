"""Clean version of the custom Xception backbone supplied with the project."""

from pathlib import Path

from tensorflow.keras.layers import (
    Activation,
    Add,
    BatchNormalization,
    Conv2D,
    Input,
    MaxPooling2D,
    SeparableConv2D,
)
from tensorflow.keras.models import Model


def _residual_block(x, filters, prefix):
    residual = x
    for index in range(1, 4):
        x = Activation("relu", name=f"{prefix}_sepconv{index}_act")(x)
        x = SeparableConv2D(
            filters,
            3,
            padding="same",
            use_bias=False,
            name=f"{prefix}_sepconv{index}",
        )(x)
        x = BatchNormalization(name=f"{prefix}_sepconv{index}_bn")(x)
    return Add(name=f"{prefix}_add")([x, residual])


def build_xception(input_shape=(256, 256, 3), weights_path=None):
    image = Input(shape=input_shape, name="image")
    x = Conv2D(
        32,
        3,
        strides=2,
        padding="same",
        use_bias=False,
        name="block1_conv1",
    )(image)
    c1 = x
    x = BatchNormalization(name="block1_conv1_bn")(x)
    x = Activation("relu", name="block1_conv1_act")(x)
    x = Conv2D(64, 3, use_bias=False, name="block1_conv2")(x)
    x = BatchNormalization(name="block1_conv2_bn")(x)
    x = Activation("relu", name="block1_conv2_act")(x)

    for block, filters in ((2, 128), (3, 256), (4, 728)):
        residual = Conv2D(
            filters,
            1,
            strides=2,
            padding="same",
            use_bias=False,
            name=f"block{block}_residual_conv",
        )(x)
        residual = BatchNormalization(name=f"block{block}_residual_bn")(residual)
        x = Activation("relu", name=f"block{block}_sepconv1_act")(x)
        x = SeparableConv2D(
            filters,
            3,
            padding="same",
            use_bias=False,
            name=f"block{block}_sepconv1",
        )(x)
        if block == 4:
            c2 = x
        x = BatchNormalization(name=f"block{block}_sepconv1_bn")(x)
        x = Activation("relu", name=f"block{block}_sepconv2_act")(x)
        x = SeparableConv2D(
            filters,
            3,
            padding="same",
            use_bias=False,
            name=f"block{block}_sepconv2",
        )(x)
        x = BatchNormalization(name=f"block{block}_sepconv2_bn")(x)
        x = MaxPooling2D(
            3, strides=2, padding="same", name=f"block{block}_pool"
        )(x)
        x = Add(name=f"block{block}_add")([x, residual])

    x = _residual_block(x, 728, "block5")
    x = _residual_block(x, 728, "block6")

    residual = x
    x = Activation("relu", name="block7_sepconv1_act")(x)
    x = SeparableConv2D(
        728, 3, padding="same", use_bias=False, name="block7_sepconv1"
    )(x)
    c3 = x
    x = BatchNormalization(name="block7_sepconv1_bn")(x)
    for index in (2, 3):
        x = Activation("relu", name=f"block7_sepconv{index}_act")(x)
        x = SeparableConv2D(
            728,
            3,
            padding="same",
            use_bias=False,
            name=f"block7_sepconv{index}",
        )(x)
        x = BatchNormalization(name=f"block7_sepconv{index}_bn")(x)
    x = Add(name="block7_add")([x, residual])

    x = _residual_block(x, 728, "block8")
    x = _residual_block(x, 728, "block9")

    residual = x
    x = Activation("relu", name="block10_sepconv1_act")(x)
    x = SeparableConv2D(
        728, 3, padding="same", use_bias=False, name="block10_sepconv1"
    )(x)
    c4 = x
    x = BatchNormalization(name="block10_sepconv1_bn")(x)
    for index in (2, 3):
        x = Activation("relu", name=f"block10_sepconv{index}_act")(x)
        x = SeparableConv2D(
            728,
            3,
            padding="same",
            use_bias=False,
            name=f"block10_sepconv{index}",
        )(x)
        x = BatchNormalization(name=f"block10_sepconv{index}_bn")(x)
    x = Add(name="block10_add")([x, residual])

    x = _residual_block(x, 728, "block11")
    x = _residual_block(x, 728, "block12")

    residual = Conv2D(
        1024,
        1,
        strides=2,
        padding="same",
        use_bias=False,
        name="block13_residual_conv",
    )(x)
    residual = BatchNormalization(name="block13_residual_bn")(residual)
    x = Activation("relu", name="block13_sepconv1_act")(x)
    x = SeparableConv2D(
        728, 3, padding="same", use_bias=False, name="block13_sepconv1"
    )(x)
    x = BatchNormalization(name="block13_sepconv1_bn")(x)
    x = Activation("relu", name="block13_sepconv2_act")(x)
    x = SeparableConv2D(
        1024, 3, padding="same", use_bias=False, name="block13_sepconv2"
    )(x)
    x = BatchNormalization(name="block13_sepconv2_bn")(x)
    x = MaxPooling2D(3, strides=2, padding="same", name="block13_pool")(x)
    x = Add(name="block13_add")([x, residual])

    x = SeparableConv2D(
        1536, 3, padding="same", use_bias=False, name="block14_sepconv1"
    )(x)
    x = BatchNormalization(name="block14_sepconv1_bn")(x)
    x = Activation("relu", name="block14_sepconv1_act")(x)
    x = SeparableConv2D(
        2048, 3, padding="same", use_bias=False, name="block14_sepconv2"
    )(x)
    x = BatchNormalization(name="block14_sepconv2_bn")(x)
    c5 = Activation("relu", name="block14_sepconv2_act")(x)

    model = Model(image, c5, name="custom_xception")
    if weights_path:
        weights_path = Path(weights_path)
        if not weights_path.is_file():
            raise FileNotFoundError(f"Xception weights not found: {weights_path}")
        model.load_weights(weights_path)
    return model, (c1, c2, c3, c4, c5)
