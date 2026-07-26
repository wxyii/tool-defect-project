"""Convolutional Block Attention Module used by the retained models."""

from tensorflow.keras import backend as K
from tensorflow.keras.layers import (
    Activation,
    Add,
    Concatenate,
    Conv2D,
    Dense,
    GlobalAveragePooling2D,
    GlobalMaxPooling2D,
    Lambda,
    Multiply,
    Reshape,
)


def channel_attention(input_feature, ratio=7):
    channel = int(input_feature.shape[-1])
    hidden_units = max(1, channel // ratio)
    shared_one = Dense(
        hidden_units,
        activation="relu",
        kernel_initializer="he_normal",
        use_bias=True,
        bias_initializer="zeros",
    )
    shared_two = Dense(
        channel,
        activation="sigmoid",
        kernel_initializer="he_normal",
        use_bias=True,
        bias_initializer="zeros",
    )

    average = Reshape((1, 1, channel))(GlobalAveragePooling2D()(input_feature))
    maximum = Reshape((1, 1, channel))(GlobalMaxPooling2D()(input_feature))
    average = shared_two(shared_one(average))
    maximum = shared_two(shared_one(maximum))
    weights = Activation("hard_sigmoid")(Add()([average, maximum]))
    return Multiply()([input_feature, weights])


def spatial_attention(input_feature):
    average = Lambda(
        lambda value: K.mean(value, axis=3, keepdims=True),
        output_shape=lambda shape: shape[:-1] + (1,),
    )(input_feature)
    maximum = Lambda(
        lambda value: K.max(value, axis=3, keepdims=True),
        output_shape=lambda shape: shape[:-1] + (1,),
    )(input_feature)
    combined = Concatenate(axis=3)([average, maximum])
    weights = Conv2D(
        filters=1,
        kernel_size=7,
        activation="hard_sigmoid",
        strides=1,
        padding="same",
        kernel_initializer="he_normal",
        use_bias=False,
    )(combined)
    return Multiply()([input_feature, weights])


def cbam_block(input_feature, ratio=7):
    return spatial_attention(channel_attention(input_feature, ratio=ratio))
