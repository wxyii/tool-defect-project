"""Losses and foreground metrics for extremely sparse defect masks."""

import tensorflow as tf


_EPSILON = tf.keras.backend.epsilon()


@tf.keras.utils.register_keras_serializable(package="tool_defect")
def focal_tversky_loss(y_true, y_pred, alpha=0.3, beta=0.7, gamma=0.75):
    y_true_defect = tf.cast(y_true[..., 1], tf.float32)
    y_pred_defect = tf.cast(y_pred[..., 1], tf.float32)
    axes = tuple(range(1, len(y_true_defect.shape)))
    true_positive = tf.reduce_sum(y_true_defect * y_pred_defect, axis=axes)
    false_positive = tf.reduce_sum(
        (1.0 - y_true_defect) * y_pred_defect, axis=axes
    )
    false_negative = tf.reduce_sum(
        y_true_defect * (1.0 - y_pred_defect), axis=axes
    )
    tversky = (true_positive + _EPSILON) / (
        true_positive
        + alpha * false_positive
        + beta * false_negative
        + _EPSILON
    )
    return tf.reduce_mean(tf.pow(1.0 - tversky, gamma))


@tf.keras.utils.register_keras_serializable(package="tool_defect")
def foreground_focal_bce(y_true, y_pred, alpha=0.75, gamma=2.0):
    target = tf.cast(y_true[..., 1], tf.float32)
    probability = tf.clip_by_value(
        tf.cast(y_pred[..., 1], tf.float32), _EPSILON, 1.0 - _EPSILON
    )
    positive = -alpha * target * tf.pow(1.0 - probability, gamma) * tf.math.log(
        probability
    )
    negative = (
        -(1.0 - alpha)
        * (1.0 - target)
        * tf.pow(probability, gamma)
        * tf.math.log(1.0 - probability)
    )
    return tf.reduce_mean(positive + negative)


@tf.keras.utils.register_keras_serializable(package="tool_defect")
def combined_segmentation_loss(y_true, y_pred):
    return 0.5 * focal_tversky_loss(y_true, y_pred) + 0.5 * foreground_focal_bce(
        y_true, y_pred
    )


@tf.keras.utils.register_keras_serializable(package="tool_defect")
def balanced_focal_tversky_loss(y_true, y_pred):
    """Symmetric foreground overlap loss that does not prefer recall over precision."""
    return focal_tversky_loss(
        y_true,
        y_pred,
        alpha=0.5,
        beta=0.5,
        gamma=0.75,
    )


@tf.keras.utils.register_keras_serializable(package="tool_defect")
def balanced_foreground_focal_bce(y_true, y_pred):
    """Focal foreground BCE with equal positive and negative class weighting."""
    return foreground_focal_bce(y_true, y_pred, alpha=0.5, gamma=2.0)


@tf.keras.utils.register_keras_serializable(package="tool_defect")
def balanced_segmentation_loss(y_true, y_pred):
    return 0.5 * balanced_focal_tversky_loss(
        y_true, y_pred
    ) + 0.5 * balanced_foreground_focal_bce(y_true, y_pred)


class _DefectConfusionMetric(tf.keras.metrics.Metric):
    def __init__(self, name, **kwargs):
        super().__init__(name=name, **kwargs)
        self.true_positive = self.add_weight(name="tp", initializer="zeros")
        self.false_positive = self.add_weight(name="fp", initializer="zeros")
        self.false_negative = self.add_weight(name="fn", initializer="zeros")

    def update_state(self, y_true, y_pred, sample_weight=None):
        truth = tf.equal(tf.argmax(y_true, axis=-1), 1)
        prediction = tf.equal(tf.argmax(y_pred, axis=-1), 1)
        truth = tf.cast(truth, self.dtype)
        prediction = tf.cast(prediction, self.dtype)
        if sample_weight is not None:
            weight = tf.cast(sample_weight, self.dtype)
            weight = tf.broadcast_to(weight, tf.shape(truth))
        else:
            weight = 1.0
        self.true_positive.assign_add(
            tf.reduce_sum(weight * truth * prediction)
        )
        self.false_positive.assign_add(
            tf.reduce_sum(weight * (1.0 - truth) * prediction)
        )
        self.false_negative.assign_add(
            tf.reduce_sum(weight * truth * (1.0 - prediction))
        )

    def reset_state(self):
        for variable in self.variables:
            variable.assign(0.0)


@tf.keras.utils.register_keras_serializable(package="tool_defect")
class DefectIoU(_DefectConfusionMetric):
    def __init__(self, name="defect_iou", **kwargs):
        super().__init__(name=name, **kwargs)

    def result(self):
        return tf.math.divide_no_nan(
            self.true_positive,
            self.true_positive + self.false_positive + self.false_negative,
        )


@tf.keras.utils.register_keras_serializable(package="tool_defect")
class DefectDice(_DefectConfusionMetric):
    def __init__(self, name="defect_dice", **kwargs):
        super().__init__(name=name, **kwargs)

    def result(self):
        return tf.math.divide_no_nan(
            2.0 * self.true_positive,
            2.0 * self.true_positive
            + self.false_positive
            + self.false_negative,
        )


@tf.keras.utils.register_keras_serializable(package="tool_defect")
class DefectPrecision(_DefectConfusionMetric):
    def __init__(self, name="defect_precision", **kwargs):
        super().__init__(name=name, **kwargs)

    def result(self):
        return tf.math.divide_no_nan(
            self.true_positive, self.true_positive + self.false_positive
        )


@tf.keras.utils.register_keras_serializable(package="tool_defect")
class DefectRecall(_DefectConfusionMetric):
    def __init__(self, name="defect_recall", **kwargs):
        super().__init__(name=name, **kwargs)

    def result(self):
        return tf.math.divide_no_nan(
            self.true_positive, self.true_positive + self.false_negative
        )
