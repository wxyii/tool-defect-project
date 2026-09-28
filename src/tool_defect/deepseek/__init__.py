"""DeepSeek 视觉模型验证工具。

该包只负责独立验证，不修改现有 TensorFlow 推理入口。
"""

from tool_defect.deepseek.client import DeepSeekVisionClient

__all__ = ["DeepSeekVisionClient"]
