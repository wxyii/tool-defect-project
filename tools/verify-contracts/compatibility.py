#!/usr/bin/env python3
"""生成并检查 v1 契约兼容表面。"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
BASELINE = CONTRACTS / "compatibility" / "v1-baseline.json"
METHODS = {"get", "post", "put", "patch", "delete"}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def schema_surface(schema: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not isinstance(schema, dict):
        return result
    if "enum" in schema:
        result[f"{prefix or '/'}#enum"] = sorted(schema["enum"])
    if "type" in schema:
        value = schema["type"]
        result[f"{prefix or '/'}#type"] = sorted(value) if isinstance(value, list) else value
    if "const" in schema:
        result[f"{prefix or '/'}#const"] = schema["const"]
    if "required" in schema:
        result[f"{prefix or '/'}#required"] = sorted(schema["required"])
    for name, child in schema.get("properties", {}).items():
        result[f"{prefix}/{name}#property"] = True
        result.update(schema_surface(child, f"{prefix}/{name}"))
    for name, child in schema.get("$defs", {}).items():
        result.update(schema_surface(child, f"{prefix}/$defs/{name}"))
    return result


def snapshot() -> dict[str, Any]:
    schemas: dict[str, Any] = {}
    for path in sorted((CONTRACTS / "json-schema").glob("*.json")):
        schemas[path.name] = schema_surface(load(path))

    api = load(CONTRACTS / "openapi" / "tool-defect-api-v1.json")
    openapi_schemas = {
        name: schema_surface(schema)
        for name, schema in sorted(api["components"]["schemas"].items())
    }
    operations: dict[str, Any] = {}
    for path, item in sorted(api["paths"].items()):
        for method, operation in sorted(item.items()):
            if method not in METHODS:
                continue
            operations[f"{method.upper()} {path}"] = {
                "operation_id": operation["operationId"],
                "responses": sorted(operation["responses"]),
                "has_request_body": "requestBody" in operation,
            }
    asyncapi = load(CONTRACTS / "asyncapi" / "inference-events-v1.json")
    consumers = load(CONTRACTS / "consumers" / "v1-consumers.json")
    return {
        "baseline_format": 1,
        "contract_major": 1,
        "json_schema_surfaces": schemas,
        "openapi_operations": operations,
        "openapi_schema_surfaces": openapi_schemas,
        "asyncapi_channels": sorted(asyncapi["channels"]),
        "asyncapi_operations": sorted(asyncapi["operations"]),
        "consumer_operations": {
            item["consumer_id"]: {
                "http": sorted(item["http_operations"]),
                "events": sorted(item["event_operations"]),
            }
            for item in consumers["consumers"]
        },
    }


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for section in ("json_schema_surfaces", "openapi_schema_surfaces"):
        for schema_name, old_surface in baseline.get(section, {}).items():
            if schema_name not in current.get(section, {}):
                errors.append(f"删除模式 {section}/{schema_name}")
                continue
            new_surface = current[section][schema_name]
            for key, old_values in old_surface.items():
                if key not in new_surface:
                    errors.append(f"{section}/{schema_name} 删除约束表面 {key}")
                    continue
                if key.endswith("#enum"):
                    removed = set(old_values) - set(new_surface[key])
                    if removed:
                        errors.append(f"{schema_name} {key} 删除枚举 {sorted(removed)}")
                elif key.endswith("#required"):
                    # 删除既有必填字段会改变响应保证，也视为 v1 破坏性变更。
                    removed = set(old_values) - set(new_surface[key])
                    added = set(new_surface[key]) - set(old_values)
                    if removed:
                        errors.append(f"{schema_name} {key} 删除必填 {sorted(removed)}")
                    if added:
                        errors.append(f"{schema_name} {key} 新增必填 {sorted(added)}")
                elif new_surface[key] != old_values:
                    errors.append(f"{schema_name} 修改字段约束 {key}")
    for operation, old in baseline["openapi_operations"].items():
        if operation not in current["openapi_operations"]:
            errors.append(f"删除接口 {operation}")
            continue
        new = current["openapi_operations"][operation]
        if new["operation_id"] != old["operation_id"]:
            errors.append(f"{operation} 修改 operationId")
        removed_responses = set(old["responses"]) - set(new["responses"])
        if removed_responses:
            errors.append(f"{operation} 删除响应 {sorted(removed_responses)}")
        if old["has_request_body"] and not new["has_request_body"]:
            errors.append(f"{operation} 删除请求体")
    for name in ("asyncapi_channels", "asyncapi_operations"):
        removed = set(baseline[name]) - set(current[name])
        if removed:
            errors.append(f"{name} 删除 {sorted(removed)}")
    for consumer, old in baseline.get("consumer_operations", {}).items():
        new = current["consumer_operations"].get(consumer)
        if new is None:
            errors.append(f"删除消费者 {consumer}")
            continue
        for protocol in ("http", "events"):
            removed = set(old[protocol]) - set(new[protocol])
            if removed:
                errors.append(f"{consumer} 删除 {protocol} 消费契约 {sorted(removed)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    current = snapshot()
    if args.write_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(
            json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"已写入兼容基线：{BASELINE.relative_to(ROOT)}")
        return 0
    if not BASELINE.exists():
        print("兼容检查失败：基线不存在", file=sys.stderr)
        return 1
    baseline = load(BASELINE)
    errors = compare(baseline, current)
    if args.self_test:
        damaged = copy.deepcopy(current)
        removed = next(iter(damaged["openapi_operations"]))
        del damaged["openapi_operations"][removed]
        if not compare(baseline, damaged):
            print("兼容检查自测失败：未识别端点删除", file=sys.stderr)
            return 1
        damaged_field = copy.deepcopy(current)
        schema_name = next(iter(damaged_field["openapi_schema_surfaces"]))
        surface = damaged_field["openapi_schema_surfaces"][schema_name]
        property_key = next(key for key in surface if key.endswith("#property"))
        del surface[property_key]
        if not compare(baseline, damaged_field):
            print("兼容检查自测失败：未识别字段删除", file=sys.stderr)
            return 1
    if errors:
        print("检测到 v1 破坏性变更：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("v1 兼容检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
