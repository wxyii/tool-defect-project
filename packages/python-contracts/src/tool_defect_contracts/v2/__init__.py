# 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
# 契约主版本: 2；源哈希: 22c752871f6e08eabb41421367fff400af7513cc7fdfc2a1a5cab551308ca2f9
from .client import ApiClientV2
from .models import CONTRACT_MAJOR_VERSION, CONTRACT_SOURCE_SHA256

__all__ = ["ApiClientV2", "CONTRACT_MAJOR_VERSION", "CONTRACT_SOURCE_SHA256"]
