# 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
# 契约主版本: 1；源哈希: 698d11ac5202bb62df31a09ed1c46be7280d905bc497c612fa9ab557e35b26cc
from .client import ApiClient
from .models import CONTRACT_MAJOR_VERSION, CONTRACT_SOURCE_SHA256, ObjectReference

__all__ = ["ApiClient", "CONTRACT_MAJOR_VERSION", "CONTRACT_SOURCE_SHA256", "ObjectReference"]
