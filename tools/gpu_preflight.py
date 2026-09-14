"""Run a small TensorFlow convolution to verify the server GPU runtime."""

import json

import tensorflow as tf


def main():
    physical = tf.config.list_physical_devices("GPU")
    if not physical:
        raise SystemExit("未发现 TensorFlow GPU 设备")
    logical = tf.config.list_logical_devices("GPU")
    inputs = tf.zeros((1, 64, 64, 3), dtype=tf.float32)
    outputs = tf.keras.layers.Conv2D(8, 3, padding="valid")(inputs)
    if tuple(outputs.shape) != (1, 62, 62, 8):
        raise SystemExit(f"GPU 卷积自检输出尺寸异常：{outputs.shape}")
    print(
        json.dumps(
            {
                "tensorflow": tf.__version__,
                "cuda_build": tf.sysconfig.get_build_info().get("cuda_version"),
                "cudnn_build": tf.sysconfig.get_build_info().get("cudnn_version"),
                "physical_gpus": [device.name for device in physical],
                "logical_gpus": [device.name for device in logical],
                "convolution_output": list(outputs.shape),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
