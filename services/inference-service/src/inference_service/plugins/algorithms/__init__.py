"""标准算法插件。"""

from inference_service.plugins.algorithms.keras_classification import (
    KerasClassificationAdapter,
)
from inference_service.plugins.algorithms.keras_multitask import (
    KerasMultitaskAdapter,
)
from inference_service.plugins.algorithms.polar_anomaly import (
    PolarAnomalyAdapter,
)

__all__ = [
    "KerasClassificationAdapter",
    "KerasMultitaskAdapter",
    "PolarAnomalyAdapter",
]
