# 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
# 契约主版本: 2；源哈希: ff943178ec32e8d1e936321170d1a28f70eab0edcd15a37884c81f148abb5ad4
from .client import ApiClientV2
from .models import CONTRACT_MAJOR_VERSION, CONTRACT_SOURCE_SHA256

__all__ = ["ApiClientV2", "CONTRACT_MAJOR_VERSION", "CONTRACT_SOURCE_SHA256"]
