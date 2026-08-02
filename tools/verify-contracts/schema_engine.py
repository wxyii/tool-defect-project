#!/usr/bin/env python3
"""项目内使用的 JSON Schema 2020-12 最小验证器。

只实现本仓库契约实际使用的关键字；遇到未知关键字会显式失败，避免误把未验证
的约束当作通过。实现不依赖网络，适用于干净的离线持续集成环境。
"""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


ANNOTATIONS = {"$schema", "$id", "title", "description", "default", "examples", "readOnly", "writeOnly"}
SUPPORTED = {
    "$ref",
    "$defs",
    "type",
    "required",
    "properties",
    "additionalProperties",
    "enum",
    "const",
    "pattern",
    "format",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "uniqueItems",
    "items",
    "oneOf",
    "maxProperties",
}


class ValidationError(ValueError):
    def __init__(self, keyword: str, path: str, detail: str) -> None:
        self.keyword = keyword
        self.path = path or "/"
        super().__init__(f"{self.keyword} {self.path}: {detail}")


class SchemaEngine:
    def __init__(self) -> None:
        self._documents: dict[Path, Any] = {}

    def load(self, path: Path) -> Any:
        path = path.resolve()
        if path not in self._documents:
            self._documents[path] = json.loads(path.read_text(encoding="utf-8"))
        return self._documents[path]

    @staticmethod
    def pointer(document: Any, fragment: str) -> Any:
        if not fragment:
            return document
        if not fragment.startswith("/"):
            raise ValidationError("$ref", "/", f"不支持的片段 {fragment!r}")
        current = document
        for raw in fragment[1:].split("/"):
            token = raw.replace("~1", "/").replace("~0", "~")
            current = current[int(token)] if isinstance(current, list) else current[token]
        return current

    def dereference(self, ref: str, document_path: Path) -> tuple[Any, Path]:
        file_part, _, fragment = ref.partition("#")
        target_path = (
            (document_path.parent / file_part).resolve()
            if file_part
            else document_path.resolve()
        )
        return self.pointer(self.load(target_path), fragment), target_path

    def validate_file(self, instance: Any, schema_path: Path) -> None:
        self.validate(instance, self.load(schema_path), schema_path.resolve(), "")

    def validate(
        self,
        instance: Any,
        schema: Any,
        document_path: Path,
        instance_path: str,
    ) -> None:
        if isinstance(schema, bool):
            if not schema:
                raise ValidationError("falseSchema", instance_path, "布尔模式拒绝实例")
            return
        if not isinstance(schema, dict):
            raise ValidationError("schema", instance_path, "模式不是对象")

        unknown = set(schema) - ANNOTATIONS - SUPPORTED
        if unknown:
            raise ValidationError(
                "unsupportedKeyword", instance_path, ", ".join(sorted(unknown))
            )

        if "$ref" in schema:
            target, target_path = self.dereference(schema["$ref"], document_path)
            self.validate(instance, target, target_path, instance_path)
            return

        if "oneOf" in schema:
            matches = 0
            failures: list[str] = []
            for option in schema["oneOf"]:
                try:
                    self.validate(instance, option, document_path, instance_path)
                    matches += 1
                except ValidationError as exc:
                    failures.append(str(exc))
            if matches != 1:
                raise ValidationError(
                    "oneOf",
                    instance_path,
                    f"应恰好匹配一个分支，实际 {matches}；{'; '.join(failures[:2])}",
                )

        if "type" in schema:
            allowed = schema["type"]
            if isinstance(allowed, str):
                allowed = [allowed]
            if not any(self._matches_type(instance, name) for name in allowed):
                raise ValidationError(
                    "type", instance_path, f"实际 {type(instance).__name__}，预期 {allowed}"
                )

        if "const" in schema and instance != schema["const"]:
            raise ValidationError("const", instance_path, f"预期 {schema['const']!r}")
        if "enum" in schema and instance not in schema["enum"]:
            raise ValidationError("enum", instance_path, f"{instance!r} 不在枚举中")

        if isinstance(instance, dict):
            required = schema.get("required", [])
            for name in required:
                if name not in instance:
                    raise ValidationError("required", instance_path, f"缺少字段 {name}")
            properties = schema.get("properties", {})
            if schema.get("additionalProperties") is False:
                extra = set(instance) - set(properties)
                if extra:
                    raise ValidationError(
                        "additionalProperties",
                        instance_path,
                        f"未知字段 {sorted(extra)}",
                    )
            elif isinstance(schema.get("additionalProperties"), dict):
                for name in set(instance) - set(properties):
                    self.validate(
                        instance[name],
                        schema["additionalProperties"],
                        document_path,
                        f"{instance_path}/{name}",
                    )
            if "maxProperties" in schema and len(instance) > schema["maxProperties"]:
                raise ValidationError("maxProperties", instance_path, "对象字段过多")
            for name, value in instance.items():
                if name in properties:
                    child_path = f"{instance_path}/{name}"
                    self.validate(value, properties[name], document_path, child_path)

        if isinstance(instance, list):
            if "minItems" in schema and len(instance) < schema["minItems"]:
                raise ValidationError("minItems", instance_path, "数组过短")
            if "maxItems" in schema and len(instance) > schema["maxItems"]:
                raise ValidationError("maxItems", instance_path, "数组过长")
            if schema.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in instance}) != len(instance):
                raise ValidationError("uniqueItems", instance_path, "数组元素不唯一")
            if "items" in schema:
                for index, value in enumerate(instance):
                    self.validate(
                        value, schema["items"], document_path, f"{instance_path}/{index}"
                    )

        if isinstance(instance, str):
            if "minLength" in schema and len(instance) < schema["minLength"]:
                raise ValidationError("minLength", instance_path, "字符串过短")
            if "maxLength" in schema and len(instance) > schema["maxLength"]:
                raise ValidationError("maxLength", instance_path, "字符串过长")
            if "pattern" in schema and re.search(schema["pattern"], instance) is None:
                raise ValidationError("pattern", instance_path, "不匹配模式")
            if "format" in schema:
                self._validate_format(instance, schema["format"], instance_path)

        if isinstance(instance, (int, float)) and not isinstance(instance, bool):
            if not math.isfinite(instance):
                raise ValidationError("number", instance_path, "数值必须有限")
            if "minimum" in schema and instance < schema["minimum"]:
                raise ValidationError("minimum", instance_path, "数值过小")
            if "maximum" in schema and instance > schema["maximum"]:
                raise ValidationError("maximum", instance_path, "数值过大")

    @staticmethod
    def _matches_type(value: Any, expected: str) -> bool:
        checks = {
            "null": value is None,
            "boolean": isinstance(value, bool),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        }
        if expected not in checks:
            raise ValidationError("type", "/", f"不支持类型 {expected}")
        return checks[expected]

    @staticmethod
    def _validate_format(value: str, format_name: str, path: str) -> None:
        try:
            if format_name == "uuid":
                uuid.UUID(value)
            elif format_name == "date-time":
                if not value.endswith("Z"):
                    raise ValueError("必须为 UTC")
                datetime.fromisoformat(value[:-1] + "+00:00")
            elif format_name == "uri":
                if not re.match(r"^https?://[^/\s]+(?:/.*)?$", value):
                    raise ValueError("不是绝对 HTTP(S) 地址")
            else:
                raise ValidationError("unsupportedFormat", path, format_name)
        except (ValueError, AttributeError) as exc:
            raise ValidationError("format", path, str(exc)) from exc
