"""School-designated final classification and segmentation training model."""

from tensorflow.keras import regularizers
from tensorflow.keras.layers import (
    Concatenate,
    Conv2D,
    Dense,
    Dropout,
    Flatten,
    GlobalAveragePooling2D,
    MaxPooling2D,
    UpSampling2D,
)
from tensorflow.keras.models import Model

from tool_defect.models.cbam import cbam_block
from tool_defect.models.xception import build_xception


def _classification_head(features):
    attended = [cbam_block(feature) for feature in features]
    aligned = [
        MaxPooling2D(pool_size=size, strides=size, padding="same")(
            Conv2D(256, 1, activation="relu", padding="same")(feature)
        )
        for feature, size in zip(attended, (16, 4, 2, 2, 1))
    ]
    x = Concatenate(axis=3)(aligned)
    x = Conv2D(256, 1, activation="relu", padding="same")(x)
    x = GlobalAveragePooling2D()(x)
    x = Dropout(0.4)(x)
    x = Flatten()(x)
    x = Dense(256, activation="relu", kernel_regularizer=regularizers.l2(0.001))(x)
    x = Dense(128, activation="relu", kernel_regularizer=regularizers.l2(0.001))(x)
    return Dense(2, activation="softmax", name="cla_out")(x)


def _segmentation_head(features):
    c1, c2, c3, c4, c5 = features
    up6 = Conv2D(728, 2, activation="relu", padding="same")(
        UpSampling2D(2)(c5)
    )
    conv6 = Concatenate(axis=3)([c4, up6])
    conv6 = Conv2D(512, 3, activation="relu", padding="same")(conv6)
    conv6 = Conv2D(256, 3, activation="relu", padding="same")(conv6)

    up7 = Conv2D(728, 2, activation="relu", padding="same")(conv6)
    conv7 = Concatenate(axis=3)([c3, up7])
    conv7 = Conv2D(512, 3, activation="relu", padding="same")(conv7)
    conv7 = Conv2D(256, 3, activation="relu", padding="same")(conv7)

    up8 = Conv2D(728, 2, activation="relu", padding="same")(
        UpSampling2D(2)(conv7)
    )
    conv8 = Concatenate(axis=3)([c2, up8])
    conv8 = Conv2D(256, 3, activation="relu", padding="same")(conv8)
    conv8 = Conv2D(128, 3, activation="relu", padding="same")(conv8)

    up9 = Conv2D(32, 2, activation="relu", padding="same")(
        UpSampling2D(4)(conv8)
    )
    conv9 = Concatenate(axis=3)([c1, up9])
    conv9 = Conv2D(128, 3, activation="relu", padding="same")(conv9)
    conv9 = Conv2D(64, 3, activation="relu", padding="same")(conv9)
    up10 = Conv2D(32, 2, activation="relu", padding="same")(
        UpSampling2D(2)(conv9)
    )
    return Conv2D(2, 1, activation="softmax", name="seg_out")(up10)


def build_multitask(
    input_shape=(256, 256, 3),
    backbone_weights=None,
):
    backbone, features = build_xception(
        input_shape=input_shape,
        weights_path=backbone_weights,
    )
    for layer in backbone.layers[:-10]:
        layer.trainable = False
    classification = _classification_head(features)
    segmentation = _segmentation_head(features)
    return Model(
        backbone.input,
        [classification, segmentation],
        name="xception_cbam_multitask",
    )
