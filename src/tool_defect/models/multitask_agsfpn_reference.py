"""AG+FPN ablation retained as a runnable reference, not the default model.

The supplied materials do not prove that this source is strictly identical to
the architecture used to create artifacts/multitask/weights.h5.
"""

from tensorflow.keras import regularizers
from tensorflow.keras.layers import (
    Add,
    BatchNormalization,
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

from tool_defect.models.attention_gate import attention_gate
from tool_defect.models.cbam import cbam_block
from tool_defect.models.xception import build_xception


def build_multitask_agsfpn_reference(
    input_shape=(256, 256, 3),
    backbone_weights=None,
):
    backbone, features = build_xception(
        input_shape=input_shape,
        weights_path=backbone_weights,
    )
    for layer in backbone.layers[:-10]:
        layer.trainable = False
    c1, c2, c3, c4, c5 = features

    attended = [cbam_block(feature) for feature in features]
    aligned = [
        MaxPooling2D(pool_size=size, strides=size, padding="same")(
            Conv2D(256, 1, activation="relu", padding="same")(feature)
        )
        for feature, size in zip(attended, (16, 4, 2, 2, 1))
    ]
    classification_features = Concatenate(axis=3)(aligned)

    p5 = Conv2D(256, 1, activation="relu", padding="same")(c5)
    p4 = Add()(
        [
            UpSampling2D(2)(p5),
            Conv2D(256, 1, activation="relu", padding="same")(c4),
        ]
    )
    p4 = Conv2D(256, 3, activation="relu", padding="same")(p4)
    p3 = Add()(
        [
            p4,
            Conv2D(256, 1, activation="relu", padding="same")(c3),
        ]
    )
    p3 = Conv2D(256, 3, activation="relu", padding="same")(p3)
    p2 = Add()(
        [
            UpSampling2D(2)(p3),
            Conv2D(256, 1, activation="relu", padding="same")(c2),
        ]
    )
    p2 = Conv2D(256, 3, activation="relu", padding="same")(p2)

    x = Conv2D(256, 1, activation="relu", padding="same")(
        classification_features
    )
    x = BatchNormalization()(x)
    x = GlobalAveragePooling2D()(x)
    x = Dropout(0.4)(x)
    x = Flatten()(x)
    x = Dense(256, activation="relu", kernel_regularizer=regularizers.l2(0.01))(x)
    x = Dense(128, activation="relu", kernel_regularizer=regularizers.l2(0.01))(x)
    classification = Dense(2, activation="softmax", name="cla_out")(x)

    a4 = attention_gate(p4, p5)
    conv6 = Concatenate(axis=3)([a4, UpSampling2D(2)(p5)])
    conv6 = Conv2D(512, 3, activation="relu", padding="same")(conv6)
    conv6 = Conv2D(256, 3, activation="relu", padding="same")(conv6)

    a3 = attention_gate(p3, conv6)
    conv7 = Concatenate(axis=3)([a3, conv6])
    conv7 = Conv2D(512, 3, activation="relu", padding="same")(conv7)
    conv7 = Conv2D(256, 3, activation="relu", padding="same")(conv7)

    a2 = attention_gate(p2, conv7)
    conv8 = Concatenate(axis=3)([a2, UpSampling2D(2)(conv7)])
    conv8 = Conv2D(256, 3, activation="relu", padding="same")(conv8)
    conv8 = Conv2D(128, 3, activation="relu", padding="same")(conv8)

    a1 = attention_gate(c1, conv8)
    up9 = Conv2D(32, 2, activation="relu", padding="same")(
        UpSampling2D(4)(conv8)
    )
    conv9 = Concatenate(axis=3)([a1, up9])
    conv9 = Conv2D(128, 3, activation="relu", padding="same")(conv9)
    conv9 = Conv2D(64, 3, activation="relu", padding="same")(conv9)
    up10 = Conv2D(32, 2, activation="relu", padding="same")(
        UpSampling2D(2)(conv9)
    )
    segmentation = Conv2D(2, 1, activation="softmax", name="seg_out")(up10)
    return Model(
        backbone.input,
        [classification, segmentation],
        name="xception_cbam_agsfpn_reference",
    )
