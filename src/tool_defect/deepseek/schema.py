"""DeepSeek JSON 输出解析与字段校验。"""

import json
import re
from typing import Any, Dict


_HAS_DEFECT = {"yes", "no", "uncertain"}
_IMAGE_QUALITY = {"usable", "unclear"}
_CERTAINTY = {"high", "medium", "low"}
_DEFECT_TYPES = {"edge_damage", "pit", "crack", "other"}


def _normalise(value: Any, aliases: Dict[str, str], field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"JSON 字段 {field} 必须是字符串")
    value = value.strip().lower()
    value = aliases.get(value, value)
    return value


def parse_json_content(content: str) -> Dict[str, Any]:
    """解析模型文本，兼容模型偶尔包裹的 Markdown JSON 代码块。"""

    if not isinstance(content, str) or not content.strip():
        raise ValueError("模型返回内容为空，无法解析 JSON")
    text = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"模型返回内容不是合法 JSON: {error.msg}") from error
    return validate_result(payload)


def validate_result(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("模型 JSON 顶层必须是对象")

    has_defect = _normalise(
        payload.get("has_defect"),
        {"是": "yes", "否": "no", "不确定": "uncertain"},
        "has_defect",
    )
    quality = _normalise(
        payload.get("image_quality"),
        {"可用": "usable", "清晰": "usable", "不清晰": "unclear", "不可用": "unclear"},
        "image_quality",
    )
    certainty = _normalise(
        payload.get("certainty"),
        {"高": "high", "中": "medium", "低": "low"},
        "certainty",
    )
    if has_defect not in _HAS_DEFECT:
        raise ValueError(f"has_defect 取值无效: {has_defect}")
    if quality not in _IMAGE_QUALITY:
        raise ValueError(f"image_quality 取值无效: {quality}")
    if certainty not in _CERTAINTY:
        raise ValueError(f"certainty 取值无效: {certainty}")

    defects = payload.get("defects", [])
    if defects is None:
        defects = []
    if not isinstance(defects, list):
        raise ValueError("defects 必须是数组")
    normalised_defects = []
    for index, defect in enumerate(defects):
        if not isinstance(defect, dict):
            raise ValueError(f"defects[{index}] 必须是对象")
        defect_type = defect.get("type", "other")
        if not isinstance(defect_type, str):
            raise ValueError(f"defects[{index}].type 必须是字符串")
        defect_type = defect_type.strip().lower()
        defect_type = {
            "边缘磨损": "edge_damage",
            "边缘崩缺": "edge_damage",
            "崩缺": "edge_damage",
            "凹坑": "pit",
            "裂纹": "crack",
        }.get(defect_type, defect_type)
        if defect_type not in _DEFECT_TYPES:
            defect_type = "other"
        location = defect.get("location", "")
        evidence = defect.get("evidence", "")
        if not isinstance(location, str) or not isinstance(evidence, str):
            raise ValueError(f"defects[{index}] 的 location/evidence 必须是字符串")
        normalised_defects.append(
            {
                "type": defect_type,
                "location": location.strip(),
                "evidence": evidence.strip(),
            }
        )

    return {
        "has_defect": has_defect,
        "image_quality": quality,
        "defects": normalised_defects,
        "certainty": certainty,
    }
