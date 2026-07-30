# 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
# 契约主版本: 1；源哈希: ed7e2561eaf84715c91514cec5e470ae170c3e94819820826fe34286543d7bde
from .client import ApiClient
from .models import CONTRACT_MAJOR_VERSION, CONTRACT_SOURCE_SHA256, ObjectReference

__all__ = ["ApiClient", "CONTRACT_MAJOR_VERSION", "CONTRACT_SOURCE_SHA256", "ObjectReference"]
