# 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
# 契约主版本: 1；源哈希: 186ea774bef9ecad130bacc65e1e35cc88ed59f479bd8ce14ecf19a84b300795
from .client import ApiClient
from .models import CONTRACT_MAJOR_VERSION, CONTRACT_SOURCE_SHA256, ObjectReference

__all__ = ["ApiClient", "CONTRACT_MAJOR_VERSION", "CONTRACT_SOURCE_SHA256", "ObjectReference"]
