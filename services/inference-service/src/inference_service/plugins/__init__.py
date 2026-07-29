"""推理服务插件实现与注册。"""

from inference_service.plugins.cache import (
    CacheEntryState,
    CachedPreprocessor,
    PreparedBatchCache,
    preprocessing_cache_key,
)

__all__ = [
    "CacheEntryState",
    "CachedPreprocessor",
    "PreparedBatchCache",
    "preprocessing_cache_key",
]
