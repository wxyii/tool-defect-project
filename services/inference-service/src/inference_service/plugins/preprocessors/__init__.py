"""标准预处理插件。"""

from inference_service.plugins.preprocessors.adaptive_annular import (
    AdaptiveAnnularPreprocessor,
)
from inference_service.plugins.preprocessors.basic_gray_resize import (
    BasicGrayResizePreprocessor,
)
from inference_service.plugins.preprocessors.boundary_normalized import (
    BoundaryNormalizedPreprocessor,
)
from inference_service.plugins.preprocessors.polar_denoise import (
    PolarDenoisePreprocessor,
)

__all__ = [
    "AdaptiveAnnularPreprocessor",
    "BasicGrayResizePreprocessor",
    "BoundaryNormalizedPreprocessor",
    "PolarDenoisePreprocessor",
]
