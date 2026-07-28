"""Convolutional Block Attention Module used by the retained models."""

import tensorflow as tf
from tensorflow.keras.layers import (
    Activation,
    Add,
    Concatenate,
    Conv2D,
    Dense,
    GlobalAveragePooling2D,
    GlobalMaxPooling2D,
    Layer,
    Multiply,
    Reshape,
)


@tf.keras.utils.register_keras_serializable(package="tool_defect")
class ChannelMean(Layer):
    """Serializable channel mean used instead of an unsafe Lambda layer."""

    def call(self, inputs):
        return tf.reduce_mean(inputs, axis=3, keepdims=True)

    def compute_output_shape(self, input_shape):
        return tuple(input_shape[:-1]) + (1,)


@tf.keras.utils.register_keras_serializable(package="tool_defect")
class ChannelMax(Layer):
    """Serializable channel maximum used instead of an unsafe Lambda layer."""

    def call(self, inputs):
        return tf.reduce_max(inputs, axis=3, keepdims=True)

    def compute_output_shape(self, input_shape):
        return tuple(input_shape[:-1]) + (1,)


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
    average = ChannelMean()(input_feature)
    maximum = ChannelMax()(input_feature)
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
