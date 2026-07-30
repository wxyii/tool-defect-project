"""与业务后端一致的规范 JSON 编码和摘要。"""

from decimal import Decimal
import hashlib
import json
import math
from typing import Any


def encode(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (float, Decimal)):
        return _number(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(encode(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("规范 JSON 对象键必须是字符串")
        return "{" + ",".join(
            encode(key) + ":" + encode(value[key])
            for key in sorted(value)
        ) + "}"
    raise TypeError(f"规范 JSON 不支持类型：{type(value).__name__}")


def sha256(value: Any) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def _number(value: float | Decimal) -> str:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("规范 JSON 不允许非有限数字")
    decimal = Decimal(str(value))
    if not decimal.is_finite():
        raise ValueError("规范 JSON 不允许非有限数字")
    if decimal.is_zero():
        return "0"
    normalized = decimal.normalize()
    rendered = format(normalized, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered
