# 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
# 契约主版本: 2；源哈希: b30eca1ebbb6b533902ed4ba897e07c0daebd02a7ecf931154f9d2fb3ae0fc8e
from .client import ApiClientV2
from .models import CONTRACT_MAJOR_VERSION, CONTRACT_SOURCE_SHA256

__all__ = ["ApiClientV2", "CONTRACT_MAJOR_VERSION", "CONTRACT_SOURCE_SHA256"]
