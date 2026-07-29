#!/usr/bin/env python3
"""校验 P0-02 决策登记和安全默认配置。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


ALLOWED_STATUSES = {"已确认", "暂定默认值", "上线阻断", "可后置"}
ALLOWED_GATES = {f"G{number}" for number in range(8)}
SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|token|private[_-]?key|access[_-]?key|"
    r"client[_-]?secret|credential)",
    re.IGNORECASE,
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_dotted(config: dict[str, Any], dotted_key: str) -> tuple[bool, Any]:
    current: Any = config
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return False


def validate_json_schema_subset(
    value: Any,
    schema: dict[str, Any],
    path: str = "$",
) -> list[str]:
    """校验本项目模式使用的 JSON Schema 2020-12 子集。

    支持 type、required、properties、additionalProperties、items、enum、
    const、minimum、maximum、minLength、pattern、minItems 和 uniqueItems。
    """

    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type is not None:
        candidates = (
            expected_type if isinstance(expected_type, list) else [expected_type]
        )
        if not any(_type_matches(value, item) for item in candidates):
            return [
                f"{path}: 类型应为 {candidates}，实际为 {type(value).__name__}"
            ]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: 必须等于 {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 不在允许枚举 {schema['enum']!r} 中")

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}: 缺少必填字段 {name}")
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in properties:
                    errors.append(f"{path}: 不允许额外字段 {name}")
        for name, child in value.items():
            child_schema = properties.get(name)
            if child_schema:
                errors.extend(
                    validate_json_schema_subset(
                        child,
                        child_schema,
                        f"{path}.{name}",
                    )
                )

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: 数组元素数量不足")
        if schema.get("uniqueItems"):
            serialized = [
                json.dumps(item, ensure_ascii=False, sort_keys=True)
                for item in value
            ]
            if len(serialized) != len(set(serialized)):
                errors.append(f"{path}: 数组元素必须唯一")
        item_schema = schema.get("items")
        if item_schema:
            for index, child in enumerate(value):
                errors.extend(
                    validate_json_schema_subset(
                        child,
                        item_schema,
                        f"{path}[{index}]",
                    )
                )

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: 字符串长度不足")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            errors.append(f"{path}: 不匹配模式 {schema['pattern']}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: 小于最小值 {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: 大于最大值 {schema['maximum']}")
    return errors


def _find_sensitive_keys(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if SENSITIVE_KEY.search(key):
                findings.append(child_path)
            findings.extend(_find_sensitive_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_find_sensitive_keys(child, f"{path}[{index}]"))
    return findings


def validate_decision_registry(
    root: Path,
    registry: dict[str, Any],
    safe_config: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    decisions = registry.get("decisions", [])
    identifiers = [item.get("id") for item in decisions]
    if len(identifiers) != len(set(identifiers)):
        errors.append("决策编号必须唯一")

    for index, decision in enumerate(decisions):
        prefix = f"decisions[{index}]"
        if decision.get("status") not in ALLOWED_STATUSES:
            errors.append(f"{prefix}: 状态非法")
        if decision.get("latest_gate") not in ALLOWED_GATES:
            errors.append(f"{prefix}: 最迟门禁非法")
        if not decision.get("owner"):
            errors.append(f"{prefix}: 缺少负责人")
        if not decision.get("unknown_behavior"):
            errors.append(f"{prefix}: 缺少未知项安全行为")
        config_keys = decision.get("config_keys", [])
        if not config_keys:
            errors.append(f"{prefix}: 缺少配置键")
        for key in config_keys:
            exists, _ = get_dotted(safe_config, key)
            if not exists:
                errors.append(f"{prefix}: 配置键 {key} 不存在于安全默认配置")
        source_refs = decision.get("source_refs", [])
        if not source_refs:
            errors.append(f"{prefix}: 缺少来源文档")
        for source_ref in source_refs:
            relative = source_ref.split("#", 1)[0]
            if not (root / relative).is_file():
                errors.append(f"{prefix}: 来源文档不存在：{relative}")

    if safe_config.get("production_enabled") is not False:
        errors.append("现场参数未确认时 production_enabled 必须为 false")
    disposition = safe_config.get("disposition", {})
    if disposition.get("automatic_pass_enabled") is not False:
        errors.append("未知阈值下 automatic_pass_enabled 必须为 false")
    if disposition.get("unknown_threshold_action") != "HOLD":
        errors.append("未知阈值必须安全转为 HOLD")
    if disposition.get("technical_failure_action") != "HOLD":
        errors.append("技术失败必须安全转为 HOLD")
    if safe_config.get("retention", {}).get("automatic_deletion_enabled") is not False:
        errors.append("保留期未确认时禁止自动删除")

    sensitive = _find_sensitive_keys(safe_config)
    if sensitive:
        errors.append("安全默认配置含敏感凭据字段：" + ", ".join(sensitive))
    return errors


def validate_files(root: Path) -> list[str]:
    registry_path = root / "Docs/decisions/site-parameter-decisions.json"
    registry_schema_path = root / "configs/schema/site-decisions.schema.json"
    safe_config_path = root / "configs/schema/site-parameters.safe-defaults.json"
    safe_schema_path = root / "configs/schema/site-parameters.schema.json"

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry_schema = json.loads(registry_schema_path.read_text(encoding="utf-8"))
    safe_config = json.loads(safe_config_path.read_text(encoding="utf-8"))
    safe_schema = json.loads(safe_schema_path.read_text(encoding="utf-8"))

    errors = []
    errors.extend(validate_json_schema_subset(registry, registry_schema))
    errors.extend(validate_json_schema_subset(safe_config, safe_schema))
    errors.extend(validate_decision_registry(root, registry, safe_config))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repository_root(),
    )
    args = parser.parse_args(argv)
    errors = validate_files(args.repo_root.resolve())
    print(
        json.dumps(
            {"valid": not errors, "errors": errors},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
