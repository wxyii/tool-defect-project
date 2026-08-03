#!/usr/bin/env python3
"""从 v1/v2 契约确定性生成 Python、Java 与 TypeScript 类型及客户端表面。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
OPENAPI = CONTRACTS / "openapi" / "tool-defect-api-v1.json"
COMMON_SCHEMA = CONTRACTS / "json-schema" / "common-v1.schema.json"
OPENAPI_V2 = CONTRACTS / "openapi" / "tool-defect-api-v2.json"
COMMON_SCHEMA_V2 = CONTRACTS / "json-schema" / "common-v2.schema.json"
HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def source_hash(major: int = 1) -> str:
    digest = hashlib.sha256()
    paths = []
    for directory in ("json-schema", "openapi", "asyncapi"):
        paths.extend((CONTRACTS / directory).glob(f"*-v{major}.json"))
        paths.extend((CONTRACTS / directory).glob(f"*-v{major}.schema.json"))
    for path in sorted(paths):
        canonical = json.dumps(
            load(path), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest.update(path.relative_to(CONTRACTS).as_posix().encode())
        digest.update(b"\0")
        digest.update(canonical.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def metadata() -> tuple[dict[str, list[str]], list[str], str]:
    common = load(COMMON_SCHEMA)
    enums = {
        name: definition["enum"]
        for name, definition in common["$defs"].items()
        if "enum" in definition
    }
    api = load(OPENAPI)
    operations = sorted(
        operation["operationId"]
        for item in api["paths"].values()
        for method, operation in item.items()
        if method in HTTP_METHODS
    )
    return enums, operations, source_hash()


def snake_upper(value: str) -> str:
    return value.replace("-", "_").replace("/", "_").upper()


def pascal_case(value: str) -> str:
    """把文件名或契约标识转换成稳定的 TypeScript 类型名。"""

    words = [word for word in re.split(r"[^A-Za-z0-9]+", value) if word]
    return "".join(word[0].upper() + word[1:] for word in words)


def upper_first(value: str) -> str:
    if not value:
        raise ValueError("operationId 不能为空")
    return value[0].upper() + value[1:]


def json_literal(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def schema_document_type_name(path: Path) -> str:
    name = path.name
    if name.endswith(".schema.json"):
        name = name[: -len(".schema.json")]
    name = re.sub(r"-v[0-9]+$", "", name)
    return pascal_case(name)


def split_schema_ref(ref: str, current_document: Path) -> tuple[Path, str]:
    relative_path, separator, fragment = ref.partition("#")
    target = (
        current_document
        if relative_path == ""
        else (current_document.parent / relative_path).resolve()
    )
    return target.resolve(), fragment if separator else ""


def schema_ref_type_name(ref: str, current_document: Path) -> str:
    """把仓库内 JSON Schema/OpenAPI 引用映射到生成的类型名。"""

    target, fragment = split_schema_ref(ref, current_document)
    tokens = [
        token.replace("~1", "/").replace("~0", "~")
        for token in fragment.strip("/").split("/")
        if token
    ]
    if target == OPENAPI.resolve():
        if len(tokens) == 3 and tokens[:2] == ["components", "schemas"]:
            return tokens[2]
        raise ValueError(f"不支持的 OpenAPI 模式引用: {ref}")
    if target == COMMON_SCHEMA.resolve():
        if len(tokens) == 2 and tokens[0] == "$defs":
            return tokens[1]
        raise ValueError(f"不支持的公共模式引用: {ref}")

    root_name = schema_document_type_name(target)
    if not tokens:
        return root_name
    if len(tokens) == 2 and tokens[0] == "$defs":
        return f"{root_name}{tokens[1]}"
    raise ValueError(f"不支持的外部模式引用: {ref}")


def typescript_schema_type(schema: object, current_document: Path) -> str:
    """覆盖冻结 v1 契约使用的 JSON Schema 2020-12 类型子集。"""

    if schema is True:
        return "unknown"
    if schema is False:
        return "never"
    if not isinstance(schema, dict):
        raise TypeError(f"模式必须是对象或布尔值: {schema!r}")

    ref = schema.get("$ref")
    if isinstance(ref, str):
        return schema_ref_type_name(ref, current_document)
    if "const" in schema:
        return json_literal(schema["const"])
    enum = schema.get("enum")
    if isinstance(enum, list):
        return " | ".join(json_literal(value) for value in enum) or "never"

    for keyword, operator in (("oneOf", " | "), ("anyOf", " | "), ("allOf", " & ")):
        alternatives = schema.get(keyword)
        if isinstance(alternatives, list):
            rendered = [
                typescript_schema_type(alternative, current_document)
                for alternative in alternatives
            ]
            return operator.join(f"({value})" for value in rendered) or "never"

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        rendered = []
        for item in schema_type:
            branch = dict(schema)
            branch["type"] = item
            value = typescript_schema_type(branch, current_document)
            if value not in rendered:
                rendered.append(value)
        return " | ".join(rendered) or "never"

    if schema_type == "null":
        return "null"
    if schema_type == "boolean":
        return "boolean"
    if schema_type in {"integer", "number"}:
        return "number"
    if schema_type == "string":
        if schema.get("format") == "uuid":
            return "Uuid"
        return "string"
    if schema_type == "array" or "items" in schema:
        item_type = typescript_schema_type(schema.get("items", True), current_document)
        return f"ReadonlyArray<{item_type}>"
    if (
        schema_type == "object"
        or "properties" in schema
        or "additionalProperties" in schema
    ):
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise TypeError("对象模式的 properties 必须是对象")
        required_value = schema.get("required", [])
        required = set(required_value if isinstance(required_value, list) else [])
        fields = []
        for name, property_schema in sorted(properties.items()):
            optional = "" if name in required else "?"
            value_type = typescript_schema_type(property_schema, current_document)
            fields.append(
                f"readonly {json_literal(name)}{optional}: {value_type};"
            )
        object_type = "Readonly<{ " + " ".join(fields) + " }>" if fields else ""
        additional = schema.get("additionalProperties", True)
        if additional is False:
            return object_type or "Readonly<Record<string, never>>"
        if additional is True:
            additional_type = "JsonObject"
        else:
            additional_type = (
                "Readonly<Record<string, "
                + typescript_schema_type(additional, current_document)
                + ">>"
            )
        return f"({object_type} & {additional_type})" if object_type else additional_type

    return "unknown"


def walk_schema_refs(value: object) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            refs.append(ref)
        for child in value.values():
            refs.extend(walk_schema_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(walk_schema_refs(child))
    return refs


def referenced_external_schema_documents(api: dict[str, object]) -> list[Path]:
    """收集 OpenAPI 可达的外部模式；不把未引用模式混入公共包。"""

    discovered: set[Path] = set()
    pending: list[tuple[str, Path]] = [(ref, OPENAPI) for ref in walk_schema_refs(api)]
    while pending:
        ref, current_document = pending.pop()
        target, _fragment = split_schema_ref(ref, current_document)
        if target in {OPENAPI.resolve(), COMMON_SCHEMA.resolve()} or target in discovered:
            continue
        if not target.is_file() or not target.name.endswith(".schema.json"):
            raise FileNotFoundError(f"无法解析外部模式引用: {ref}")
        discovered.add(target)
        document = load(target)
        pending.extend((child_ref, target) for child_ref in walk_schema_refs(document))
    return sorted(discovered, key=lambda path: path.relative_to(CONTRACTS).as_posix())


def typescript_named_schemas(
    api: dict[str, object], common: dict[str, object]
) -> tuple[list[str], list[str]]:
    """生成公共定义、OpenAPI 组件及 OpenAPI 可达外部根模式。"""

    definitions: list[tuple[str, object, Path]] = []
    common_defs = common.get("$defs", {})
    if not isinstance(common_defs, dict):
        raise TypeError("公共模式缺少 $defs")
    definitions.extend(
        (name, schema, COMMON_SCHEMA)
        for name, schema in sorted(common_defs.items())
    )

    components = api.get("components", {})
    schemas = components.get("schemas", {}) if isinstance(components, dict) else {}
    if not isinstance(schemas, dict):
        raise TypeError("OpenAPI components.schemas 必须是对象")
    definitions.extend((name, schema, OPENAPI) for name, schema in sorted(schemas.items()))

    for document_path in referenced_external_schema_documents(api):
        document = load(document_path)
        root_name = schema_document_type_name(document_path)
        document_defs = document.get("$defs", {})
        if not isinstance(document_defs, dict):
            raise TypeError(f"{document_path.name} 的 $defs 必须是对象")
        definitions.extend(
            (f"{root_name}{name}", schema, document_path)
            for name, schema in sorted(document_defs.items())
        )
        definitions.append((root_name, document, document_path))

    names = [name for name, _schema, _path in definitions]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"TypeScript 类型名冲突: {', '.join(duplicates)}")

    output = [
        "export type JsonObject = Readonly<Record<string, unknown>>;\n",
        "export type Uuid = `${string}-${string}-${string}-${string}-${string}`;\n",
    ]
    rendered_names = ["JsonObject"]
    for name, schema, document_path in definitions:
        if name == "Uuid":
            rendered_names.append(name)
            continue
        if name == "UtcTimestamp":
            value = "`${string}Z`"
        elif name == "Traceparent":
            value = "`00-${string}-${string}-${string}`"
        else:
            value = typescript_schema_type(schema, document_path)
        output.append(f"export type {name} = {value};\n")
        rendered_names.append(name)
    return output, rendered_names


def resolve_openapi_reference(api: dict[str, object], value: object) -> object:
    """解析参数、requestBody 和 response 使用的 OpenAPI 内部引用。"""

    seen: set[str] = set()
    while isinstance(value, dict) and isinstance(value.get("$ref"), str):
        ref = value["$ref"]
        if not ref.startswith("#/"):
            return value
        if ref in seen:
            raise ValueError(f"OpenAPI 引用环: {ref}")
        seen.add(ref)
        resolved: object = api
        for raw_token in ref[2:].split("/"):
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if not isinstance(resolved, dict) or token not in resolved:
                raise KeyError(f"OpenAPI 引用不存在: {ref}")
            resolved = resolved[token]
        value = resolved
    return value


def operation_parameters(
    api: dict[str, object], path_item: dict[str, object], operation: dict[str, object]
) -> dict[str, list[tuple[str, object, bool]]]:
    merged: dict[tuple[str, str], tuple[str, object, bool]] = {}
    values: list[object] = []
    for owner in (path_item, operation):
        parameters = owner.get("parameters", [])
        if not isinstance(parameters, list):
            raise TypeError("OpenAPI parameters 必须是数组")
        values.extend(parameters)
    for raw_parameter in values:
        parameter = resolve_openapi_reference(api, raw_parameter)
        if not isinstance(parameter, dict):
            raise TypeError("OpenAPI parameter 必须是对象")
        location = parameter.get("in")
        name = parameter.get("name")
        if location not in {"path", "query", "header"} or not isinstance(name, str):
            raise ValueError(f"不支持的 OpenAPI 参数: {parameter!r}")
        parameter_schema = parameter.get("schema", True)
        required = bool(parameter.get("required", False)) or location == "path"
        merged[(location, name)] = (name, parameter_schema, required)

    grouped: dict[str, list[tuple[str, object, bool]]] = {
        "path": [],
        "query": [],
        "headers": [],
    }
    for (location, _name), parameter in sorted(merged.items()):
        group = "headers" if location == "header" else location
        grouped[group].append(parameter)
    return grouped


def request_body_type(
    api: dict[str, object], operation: dict[str, object]
) -> tuple[str | None, bool]:
    raw_body = operation.get("requestBody")
    if raw_body is None:
        return None, False
    body = resolve_openapi_reference(api, raw_body)
    if not isinstance(body, dict):
        raise TypeError("OpenAPI requestBody 必须是对象")
    content = body.get("content", {})
    if not isinstance(content, dict) or not content:
        return "unknown", bool(body.get("required", False))
    types = []
    for _media_type, media in sorted(content.items()):
        if not isinstance(media, dict):
            raise TypeError("OpenAPI media type 必须是对象")
        rendered = typescript_schema_type(media.get("schema", True), OPENAPI)
        if rendered not in types:
            types.append(rendered)
    return " | ".join(f"({value})" for value in types), bool(body.get("required", False))


def request_section_type(parameters: list[tuple[str, object, bool]]) -> str:
    fields = []
    for name, schema, required in parameters:
        optional = "" if required else "?"
        fields.append(
            f"readonly {json_literal(name)}{optional}: "
            f"{typescript_schema_type(schema, OPENAPI)};"
        )
    return "Readonly<{ " + " ".join(fields) + " }>"


def successful_response_media(
    api: dict[str, object], operation: dict[str, object]
) -> tuple[list[str], str]:
    responses = operation.get("responses", {})
    if not isinstance(responses, dict):
        raise TypeError("OpenAPI responses 必须是对象")
    media_types: set[str] = set()
    for status, raw_response in responses.items():
        if not str(status).startswith("2"):
            continue
        response = resolve_openapi_reference(api, raw_response)
        if not isinstance(response, dict):
            raise TypeError("OpenAPI response 必须是对象")
        content = response.get("content", {})
        if not isinstance(content, dict):
            raise TypeError("OpenAPI response content 必须是对象")
        media_types.update(str(media_type) for media_type in content)
    ordered = sorted(media_types)
    if not ordered:
        return ordered, "empty"
    categories = set()
    for media_type in ordered:
        if media_type == "application/json" or media_type.endswith("+json"):
            categories.add("json")
        elif media_type == "text/event-stream":
            categories.add("event-stream")
        elif media_type.startswith("text/"):
            categories.add("text")
        elif media_type.startswith("image/") or media_type == "application/octet-stream":
            categories.add("binary")
        else:
            categories.add("other")
    return ordered, next(iter(categories)) if len(categories) == 1 else "mixed"


def typescript_operations(api: dict[str, object]) -> list[dict[str, object]]:
    operations = []
    paths = api.get("paths", {})
    if not isinstance(paths, dict):
        raise TypeError("OpenAPI paths 必须是对象")
    for path, raw_path_item in paths.items():
        if not isinstance(raw_path_item, dict):
            raise TypeError("OpenAPI path item 必须是对象")
        path_item = resolve_openapi_reference(api, raw_path_item)
        if not isinstance(path_item, dict):
            raise TypeError("解析后的 OpenAPI path item 必须是对象")
        for method in HTTP_METHODS:
            raw_operation = path_item.get(method)
            if raw_operation is None:
                continue
            operation = resolve_openapi_reference(api, raw_operation)
            if not isinstance(operation, dict):
                raise TypeError("OpenAPI operation 必须是对象")
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str):
                raise ValueError(f"{method.upper()} {path} 缺少 operationId")
            parameters = operation_parameters(api, path_item, operation)
            body_type, body_required = request_body_type(api, operation)
            media_types, media_category = successful_response_media(api, operation)
            request_required = body_required or any(
                required
                for group in parameters.values()
                for _name, _schema, required in group
            )
            operations.append(
                {
                    "operation_id": operation_id,
                    "type_name": f"{upper_first(operation_id)}RequestEnvelope",
                    "method": method.upper(),
                    "path": path,
                    "parameters": parameters,
                    "body_type": body_type,
                    "body_required": body_required,
                    "request_required": request_required,
                    "response_media_types": media_types,
                    "response_media_category": media_category,
                }
            )
    return sorted(operations, key=lambda value: str(value["operation_id"]))


def typescript_client_source(
    ts_header: str, api: dict[str, object], schema_names: list[str]
) -> str:
    operations = typescript_operations(api)
    imports = sorted(name for name in schema_names if name != "JsonObject")
    output = [ts_header]
    if imports:
        output.extend(
            [
                "import type {\n",
                *(f"  {name},\n" for name in imports),
                '} from "./index.js";\n',
            ]
        )
    output.extend(
        [
            'import type { JsonObject as SchemaJsonObject } from "./index.js";\n\n',
            "export type JsonObject = SchemaJsonObject;\n",
            "export type ApiResponseMediaCategory =\n",
            '  | "json"\n  | "event-stream"\n  | "binary"\n',
            '  | "text"\n  | "empty"\n  | "other"\n  | "mixed";\n\n',
            "export const API_OPERATION_METADATA = {\n",
        ]
    )
    for operation in operations:
        output.extend(
            [
                f"  {operation['operation_id']}: {{\n",
                f"    method: {json_literal(operation['method'])},\n",
                f"    path: {json_literal(operation['path'])},\n",
                "    responseMediaCategory: "
                f"{json_literal(operation['response_media_category'])},\n",
                "    responseMediaTypes: ["
                + ", ".join(
                    json_literal(value)
                    for value in operation["response_media_types"]
                )
                + "],\n",
                "  },\n",
            ]
        )
    output.extend(
        [
            "} as const satisfies Readonly<Record<string, {\n",
            "  readonly method: string;\n",
            "  readonly path: string;\n",
            "  readonly responseMediaCategory: ApiResponseMediaCategory;\n",
            "  readonly responseMediaTypes: readonly string[];\n",
            "}>>;\n\n",
            "export type ApiOperationId = keyof typeof API_OPERATION_METADATA;\n\n",
        ]
    )

    for operation in operations:
        type_name = operation["type_name"]
        parameters = operation["parameters"]
        if not isinstance(parameters, dict):
            raise TypeError("内部错误: operation parameters 不是对象")
        output.append(f"export type {type_name} = Readonly<{{\n")
        for section in ("path", "query", "headers"):
            group = parameters[section]
            if not isinstance(group, list):
                raise TypeError("内部错误: parameter group 不是数组")
            if group:
                section_required = any(required for _name, _schema, required in group)
                optional = "" if section_required else "?"
                output.append(
                    f"  readonly {section}{optional}: {request_section_type(group)};\n"
                )
            else:
                output.append(f"  readonly {section}?: never;\n")
        body_type = operation["body_type"]
        if body_type is None:
            output.append("  readonly body?: never;\n")
        else:
            optional = "" if operation["body_required"] else "?"
            output.append(f"  readonly body{optional}: {body_type};\n")
        output.append("}>;\n\n")

    output.append("export type ApiOperationRequestMap = Readonly<{\n")
    for operation in operations:
        output.append(
            f"  readonly {operation['operation_id']}: {operation['type_name']};\n"
        )
    output.extend(["}>;\n\n", "export interface ApiClient {\n"])
    for operation in operations:
        optional = "" if operation["request_required"] else "?"
        output.append(
            f"  {operation['operation_id']}(request{optional}: "
            f"{operation['type_name']}): Promise<JsonObject>;\n"
        )
    output.append("}\n")
    return "".join(output)


def generated_files() -> dict[Path, str]:
    enums, operations, digest = metadata()
    py_header = (
        f"# 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。\n"
        f"# 契约主版本: 1；源哈希: {digest}\n"
    )
    java_header = (
        "// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。\n"
        f"// 契约主版本: 1；源哈希: {digest}\n"
    )
    ts_header = (
        "// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。\n"
        f"// 契约主版本: 1；源哈希: {digest}\n"
    )

    py_models = [
        py_header,
        "from __future__ import annotations\n\n",
        "from dataclasses import dataclass\n",
        "from enum import Enum\n",
        "from typing import Mapping, TypeAlias\n\n",
        f'CONTRACT_SOURCE_SHA256 = "{digest}"\n',
        'CONTRACT_MAJOR_VERSION = 1\n\n',
    ]
    for name, values in sorted(enums.items()):
        py_models.append(f"class {name}(str, Enum):\n")
        for value in values:
            py_models.append(f'    {snake_upper(value)} = "{value}"\n')
        py_models.append("\n")
    py_models.extend(
        [
            "@dataclass(frozen=True, slots=True)\n",
            "class ObjectReference:\n",
            "    bucket: str\n",
            "    object_key: str\n",
            "    sha256: str\n",
            "    size_bytes: int\n",
            "    media_type: str\n",
            "    object_version: str | None = None\n\n",
            "JsonObject: TypeAlias = Mapping[str, object]\n",
        ]
    )
    py_client = [
        py_header,
        "from __future__ import annotations\n\n",
        "from typing import Mapping, Protocol\n\n",
        "JsonObject = Mapping[str, object]\n\n",
        "class ApiClient(Protocol):\n",
    ]
    for operation in operations:
        py_client.append(
            f"    def {operation}(self, request: JsonObject | None = None) -> JsonObject: ...\n"
        )
    py_init = (
        py_header
        + "from .client import ApiClient\n"
        + "from .models import CONTRACT_MAJOR_VERSION, CONTRACT_SOURCE_SHA256, ObjectReference\n\n"
        + '__all__ = ["ApiClient", "CONTRACT_MAJOR_VERSION", "CONTRACT_SOURCE_SHA256", "ObjectReference"]\n'
    )

    java_enums = [
        java_header,
        "package local.tooldefect.contracts;\n\n",
        "public final class ContractEnums {\n",
        f'    public static final String SOURCE_SHA256 = "{digest}";\n',
        "    public static final int MAJOR_VERSION = 1;\n",
        "    private ContractEnums() {}\n\n",
    ]
    for name, values in sorted(enums.items()):
        java_enums.append(f"    public enum {name} {{\n")
        java_enums.append(",\n".join(f"        {snake_upper(v)}" for v in values))
        java_enums.append("\n    }\n\n")
    java_enums.append("}\n")
    java_client = [
        java_header,
        "package local.tooldefect.contracts;\n\n",
        "import java.util.Map;\n\n",
        "public interface ApiClient {\n",
    ]
    for operation in operations:
        java_client.append(
            f"    Map<String, Object> {operation}(Map<String, Object> request);\n"
        )
    java_client.append("}\n")
    java_object = (
        java_header
        + "package local.tooldefect.contracts;\n\n"
        + "public record ObjectReference(String bucket, String objectKey, String sha256, "
        + "long sizeBytes, String mediaType, String objectVersion) {}\n"
    )

    api = load(OPENAPI)
    common = load(COMMON_SCHEMA)
    ts_schema_types, ts_schema_names = typescript_named_schemas(api, common)
    ts_models = [
        ts_header,
        f'export const CONTRACT_SOURCE_SHA256 = "{digest}" as const;\n',
        "export const CONTRACT_MAJOR_VERSION = 1 as const;\n\n",
        *ts_schema_types,
    ]
    ts_client = typescript_client_source(ts_header, api, ts_schema_names)

    files = {
        ROOT
        / "packages/python-contracts/src/tool_defect_contracts/models.py": "".join(
            py_models
        ),
        ROOT
        / "packages/python-contracts/src/tool_defect_contracts/client.py": "".join(
            py_client
        ),
        ROOT
        / "packages/python-contracts/src/tool_defect_contracts/__init__.py": py_init,
        ROOT
        / "packages/java-contracts/src/main/java/local/tooldefect/contracts/ContractEnums.java": "".join(
            java_enums
        ),
        ROOT
        / "packages/java-contracts/src/main/java/local/tooldefect/contracts/ApiClient.java": "".join(
            java_client
        ),
        ROOT
        / "packages/java-contracts/src/main/java/local/tooldefect/contracts/ObjectReference.java": java_object,
        ROOT / "packages/typescript-contracts/src/index.ts": "".join(ts_models),
        ROOT / "packages/typescript-contracts/src/client.ts": ts_client,
    }
    if OPENAPI_V2.exists() and COMMON_SCHEMA_V2.exists():
        files.update(generated_v2_files())
    return files


def version_metadata(
    major: int, openapi_path: Path, common_schema_path: Path
) -> tuple[dict[str, list[str]], list[str], str]:
    common = load(common_schema_path)
    enums = {
        name: definition["enum"]
        for name, definition in common["$defs"].items()
        if "enum" in definition
    }
    api = load(openapi_path)
    operations = sorted(
        operation["operationId"]
        for item in api["paths"].values()
        for method, operation in item.items()
        if method in HTTP_METHODS
    )
    return enums, operations, source_hash(major)


def generated_v2_files() -> dict[Path, str]:
    """第二版使用独立命名空间，避免消费者链接时混入第一版类型。"""

    enums, operations, digest = version_metadata(2, OPENAPI_V2, COMMON_SCHEMA_V2)
    py_header = (
        "# 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。\n"
        f"# 契约主版本: 2；源哈希: {digest}\n"
    )
    py_models = [
        py_header,
        "from dataclasses import dataclass\n",
        "from enum import Enum\n",
        "from typing import Mapping\n\n",
        f'CONTRACT_SOURCE_SHA256 = "{digest}"\n',
        "CONTRACT_MAJOR_VERSION = 2\n\n",
    ]
    for name, values in sorted(enums.items()):
        py_models.append(f"class {name}(str, Enum):\n")
        py_models.extend(f'    {snake_upper(value)} = "{value}"\n' for value in values)
        py_models.append("\n")
    py_models.append(
        """@dataclass(frozen=True, slots=True)
class ObjectReference:
    bucket: str
    object_key: str
    sha256: str
    size_bytes: int
    media_type: str
    object_version: str | None = None

@dataclass(frozen=True, slots=True)
class BatchAggregateCounts:
    total: int
    completed: int
    defect_suspected: int
    normal: int
    inconclusive: int
    quality_rejected: int
    technical_failed: int

@dataclass(frozen=True, slots=True)
class ImageQualityCheck:
    check_type: ImageQualityCheckType
    status: ImageQualityCheckStatus
    rule_id: str
    reason_code: str
    user_hint: str
    measurement: float | None = None
    threshold: float | None = None

@dataclass(frozen=True, slots=True)
class ImageQualityResult:
    overall: ImageQualityOverall
    checker_version: str
    checks: tuple[ImageQualityCheck, ...]

@dataclass(frozen=True, slots=True)
class DetectionBatch:
    batch_id: str
    batch_no: str
    source: BatchSource
    created_by: str
    usage_stage: UsageStage
    status: BatchStatus
    counts: BatchAggregateCounts
    created_at: str
    updated_at: str
    version: int
    usage_stage_note: str | None = None

@dataclass(frozen=True, slots=True)
class DetectionBatchItem:
    batch_item_id: str
    batch_id: str
    image: ObjectReference
    status: BatchItemStatus
    created_at: str
    updated_at: str
    capture_id: str | None = None
    quality: ImageQualityResult | None = None
    algorithm_outcome: AlgorithmOutcome | None = None
    quick_review_decision: QuickReviewDecision | None = None

@dataclass(frozen=True, slots=True)
class QuickReviewRecord:
    review_record_id: str
    batch_item_id: str
    decision: QuickReviewDecision
    submitted_by: str
    submitted_at: str
    idempotency_key: str
    supersedes_record_id: str | None = None
    disposition_reference: str | None = None

@dataclass(frozen=True, slots=True)
class AdminFeedbackRecord:
    feedback_id: str
    batch_item_id: str
    label: AdminFeedbackLabel
    submitted_by: str
    submitted_at: str
    note: str | None = None
    annotation_reference: ObjectReference | None = None
    source_review_record_id: str | None = None
    supersedes_feedback_id: str | None = None
    revision: int | None = None

@dataclass(frozen=True, slots=True)
class SampleExportTarget:
    bucket: str
    object_key: str
    media_type: str
    sha256: str | None = None
    size_bytes: int | None = None
    object_version: str | None = None

@dataclass(frozen=True, slots=True)
class SampleCandidate:
    sample_candidate_id: str
    batch_item_id: str
    feedback_id: str
    status: SampleCandidateStatus
    created_at: str
    decision_note: str | None = None
    export_job_id: str | None = None
    source_snapshot: Mapping[str, object] | None = None
    latest_decision_id: str | None = None

@dataclass(frozen=True, slots=True)
class SampleExternalReceipt:
    receipt_id: str
    sample_export_job_id: str
    receiver_name: str
    recorded_by: str
    recorded_at: str
    external_reference: str | None = None
    receipt_note: str | None = None

@dataclass(frozen=True, slots=True)
class SampleExportJob:
    sample_export_job_id: str
    filter_snapshot: Mapping[str, str]
    candidate_count: int
    status: ExportJobStatus
    created_at: str
    package: ObjectReference | None = None
    manifest: ObjectReference | None = None
    failed_candidate_ids: tuple[str, ...] = ()
    exported_count: int | None = None
    failed_count: int | None = None
    expires_at: str | None = None
    external_receipts: tuple[SampleExternalReceipt, ...] = ()

@dataclass(frozen=True, slots=True)
class SampleDownloadTicket:
    ticket_id: str
    download_url: str
    expires_at: str

@dataclass(frozen=True, slots=True)
class ModelUploadSession:
    model_upload_id: str
    quarantine_object: ObjectReference
    declared_sha256: str
    status: ModelUploadStatus
    created_at: str
    expires_at: str
    model_version: str | None = None
    description: str | None = None

@dataclass(frozen=True, slots=True)
class ModelValidationResult:
    model_upload_id: str
    status: ModelValidationStatus
    package_check: str
    security_scan: str
    load_test: str
    warmup_test: str
    fixed_sample_test: str
    evidence: ObjectReference
    external_source_note: str | None = None
    safe_error: str | None = None

@dataclass(frozen=True, slots=True)
class LegacyProvenanceSnapshot:
    source_type: str
    legacy_id: str
    immutable_summary: str
    archive_reference: str
    sha256: str
    retained_until: str

@dataclass(frozen=True, slots=True)
class StandardError:
    error_code: str
    message: str
    request_id: str
    retryable: bool
    details: Mapping[str, str] | None = None

"""
    )
    py_client = [
        py_header,
        "from typing import Mapping, Protocol\n\n",
        "JsonObject = Mapping[str, object]\n\n",
        "class ApiClientV2(Protocol):\n",
    ]
    py_client.extend(
        f"    def {operation}(self, request: JsonObject | None = None) -> JsonObject: ...\n"
        for operation in operations
    )
    py_init = (
        py_header
        + "from .client import ApiClientV2\n"
        + "from .models import CONTRACT_MAJOR_VERSION, CONTRACT_SOURCE_SHA256\n\n"
        + '__all__ = ["ApiClientV2", "CONTRACT_MAJOR_VERSION", "CONTRACT_SOURCE_SHA256"]\n'
    )

    java_header = (
        "// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。\n"
        f"// 契约主版本: 2；源哈希: {digest}\n"
    )
    java_enums = [
        java_header,
        "package local.tooldefect.contracts.v2;\n\n",
        "public final class ContractEnumsV2 {\n",
        f'    public static final String SOURCE_SHA256 = "{digest}";\n',
        "    public static final int MAJOR_VERSION = 2;\n",
        "    private ContractEnumsV2() {}\n\n",
    ]
    for name, values in sorted(enums.items()):
        java_enums.append(f"    public enum {name} {{\n")
        java_enums.append(",\n".join(f"        {snake_upper(value)}" for value in values))
        java_enums.append("\n    }\n\n")
    java_enums.append("}\n")
    java_client = [
        java_header,
        "package local.tooldefect.contracts.v2;\n\n",
        "import java.util.Map;\n\n",
        "public interface ApiClientV2 {\n",
    ]
    java_client.extend(
        f"    Map<String, Object> {operation}(Map<String, Object> request);\n"
        for operation in operations
    )
    java_client.append("}\n")
    java_models = java_header + """package local.tooldefect.contracts.v2;

import java.util.List;
import java.util.Map;

public final class ContractModelsV2 {
    private ContractModelsV2() {}

    public record ObjectReference(String bucket, String objectKey, String sha256, long sizeBytes, String mediaType, String objectVersion) {}
    public record BatchAggregateCounts(long total, long completed, long defectSuspected, long normal, long inconclusive, long qualityRejected, long technicalFailed) {}
    public record ImageQualityCheck(ContractEnumsV2.ImageQualityCheckType checkType, ContractEnumsV2.ImageQualityCheckStatus status, String ruleId, String reasonCode, String userHint, Double measurement, Double threshold) {}
    public record ImageQualityResult(ContractEnumsV2.ImageQualityOverall overall, String checkerVersion, List<ImageQualityCheck> checks) {}
    public record DetectionBatch(String batchId, String batchNo, ContractEnumsV2.BatchSource source, String createdBy, ContractEnumsV2.UsageStage usageStage, String usageStageNote, ContractEnumsV2.BatchStatus status, BatchAggregateCounts counts, String createdAt, String updatedAt, long version) {}
    public record DetectionBatchItem(String batchItemId, String batchId, String captureId, ObjectReference image, ContractEnumsV2.BatchItemStatus status, ImageQualityResult quality, ContractEnumsV2.AlgorithmOutcome algorithmOutcome, ContractEnumsV2.QuickReviewDecision quickReviewDecision, String createdAt, String updatedAt) {}
    public record QuickReviewRecord(String reviewRecordId, String batchItemId, ContractEnumsV2.QuickReviewDecision decision, String submittedBy, String submittedAt, String idempotencyKey, String supersedesRecordId, String dispositionReference) {}
    public record AdminFeedbackRecord(String feedbackId, String batchItemId, ContractEnumsV2.AdminFeedbackLabel label, String note, ObjectReference annotationReference, String sourceReviewRecordId, String supersedesFeedbackId, Integer revision, String submittedBy, String submittedAt) {}
    public record SampleExportTarget(String bucket, String objectKey, String mediaType, String sha256, Long sizeBytes, String objectVersion) {}
    public record SampleCandidate(String sampleCandidateId, String batchItemId, String feedbackId, ContractEnumsV2.SampleCandidateStatus status, String decisionNote, Map<String, Object> sourceSnapshot, String latestDecisionId, String exportJobId, String createdAt) {}
    public record SampleExternalReceipt(String receiptId, String sampleExportJobId, String receiverName, String externalReference, String receiptNote, String recordedBy, String recordedAt) {}
    public record SampleExportJob(String sampleExportJobId, Map<String, String> filterSnapshot, long candidateCount, Integer exportedCount, Integer failedCount, ContractEnumsV2.ExportJobStatus status, ObjectReference packageReference, ObjectReference manifestReference, List<String> failedCandidateIds, String createdAt, String expiresAt, List<SampleExternalReceipt> externalReceipts) {}
    public record SampleDownloadTicket(String ticketId, String downloadUrl, String expiresAt) {}
    public record ModelUploadSession(String modelUploadId, ObjectReference quarantineObject, String declaredSha256, String modelVersion, String description, ContractEnumsV2.ModelUploadStatus status, String createdAt, String expiresAt) {}
    public record ModelValidationResult(String modelUploadId, ContractEnumsV2.ModelValidationStatus status, String packageCheck, String securityScan, String loadTest, String warmupTest, String fixedSampleTest, ObjectReference evidence, String externalSourceNote, String safeError) {}
    public record LegacyProvenanceSnapshot(String sourceType, String legacyId, String immutableSummary, String archiveReference, String sha256, String retainedUntil) {}
    public record StandardError(String errorCode, String message, String requestId, boolean retryable, Map<String, String> details) {}
}
"""

    ts_header = (
        "// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。\n"
        f"// 契约主版本: 2；源哈希: {digest}\n"
    )
    ts_index = [
        ts_header,
        f'export const CONTRACT_SOURCE_SHA256 = "{digest}" as const;\n',
        "export const CONTRACT_MAJOR_VERSION = 2 as const;\n\n",
        "export type JsonObject = Readonly<Record<string, unknown>>;\n\n",
    ]
    for name, values in sorted(enums.items()):
        rendered = " | ".join(json_literal(value) for value in values)
        ts_index.append(f"export type {name} = {rendered};\n")
    ts_index.append("""
export type ObjectReference = Readonly<{ bucket: string; object_key: string; sha256: string; size_bytes: number; media_type: string; object_version?: string }>;
export type BatchAggregateCounts = Readonly<{ total: number; completed: number; defect_suspected: number; normal: number; inconclusive: number; quality_rejected: number; technical_failed: number }>;
export type ImageQualityCheck = Readonly<{ check_type: ImageQualityCheckType; status: ImageQualityCheckStatus; rule_id: string; reason_code: string; user_hint: string; measurement?: number; threshold?: number }>;
export type ImageQualityResult = Readonly<{ overall: ImageQualityOverall; checker_version: string; checks: ReadonlyArray<ImageQualityCheck> }>;
export type DetectionBatch = Readonly<{ batch_id: string; batch_no: string; source: BatchSource; created_by: string; usage_stage: UsageStage; usage_stage_note?: string; status: BatchStatus; counts: BatchAggregateCounts; created_at: string; updated_at: string; version: number }>;
export type DetectionBatchItem = Readonly<{ batch_item_id: string; batch_id: string; capture_id?: string; image: ObjectReference; status: BatchItemStatus; quality?: ImageQualityResult; algorithm_outcome?: AlgorithmOutcome; quick_review_decision?: QuickReviewDecision; created_at: string; updated_at: string }>;
export type QuickReviewRecord = Readonly<{ review_record_id: string; batch_item_id: string; decision: QuickReviewDecision; submitted_by: string; submitted_at: string; idempotency_key: string; supersedes_record_id?: string; disposition_reference?: string }>;
export type AdminFeedbackRecord = Readonly<{ feedback_id: string; batch_item_id: string; label: AdminFeedbackLabel; note?: string; annotation_reference?: ObjectReference; source_review_record_id?: string; supersedes_feedback_id?: string; revision?: number; submitted_by: string; submitted_at: string }>;
export type SampleExportTarget = Readonly<{ bucket: string; object_key: string; media_type: string; sha256?: string; size_bytes?: number; object_version?: string }>;
export type SampleCandidate = Readonly<{ sample_candidate_id: string; batch_item_id: string; feedback_id: string; status: SampleCandidateStatus; decision_note?: string; source_snapshot?: JsonObject; latest_decision_id?: string; export_job_id?: string; created_at: string }>;
export type SampleExternalReceipt = Readonly<{ receipt_id: string; sample_export_job_id: string; receiver_name: string; external_reference?: string; receipt_note?: string; recorded_by: string; recorded_at: string }>;
export type SampleExportJob = Readonly<{ sample_export_job_id: string; filter_snapshot: Readonly<Record<string, string>>; candidate_count: number; exported_count?: number; failed_count?: number; status: ExportJobStatus; package?: ObjectReference; manifest?: ObjectReference; failed_candidate_ids?: ReadonlyArray<string>; external_receipts?: ReadonlyArray<SampleExternalReceipt>; created_at: string; expires_at?: string }>;
export type SampleDownloadTicket = Readonly<{ ticket_id: string; download_url: string; expires_at: string }>;
export type ModelUploadSession = Readonly<{ model_upload_id: string; quarantine_object: ObjectReference; declared_sha256: string; model_version?: string; description?: string; status: ModelUploadStatus; created_at: string; expires_at: string }>;
export type ModelValidationResult = Readonly<{ model_upload_id: string; status: ModelValidationStatus; package_check: string; security_scan: string; load_test: string; warmup_test: string; fixed_sample_test: string; evidence: ObjectReference; external_source_note?: string; safe_error?: string }>;
export type LegacyProvenanceSnapshot = Readonly<{ source_type: "LEGACY_DATASET" | "LEGACY_TRAINING"; legacy_id: string; immutable_summary: string; archive_reference: string; sha256: string; retained_until: string }>;
export type StandardError = Readonly<{ error_code: string; message: string; request_id: string; retryable: boolean; details?: Readonly<Record<string, string>> }>;
""")
    ts_client = [
        ts_header,
        "export type JsonObject = Readonly<Record<string, unknown>>;\n\n",
        "export interface ApiClientV2 {\n",
    ]
    ts_client.extend(
        f"  {operation}(request?: JsonObject): Promise<JsonObject>;\n"
        for operation in operations
    )
    ts_client.append("}\n")

    return {
        ROOT / "packages/python-contracts/src/tool_defect_contracts/v2/models.py": "".join(py_models),
        ROOT / "packages/python-contracts/src/tool_defect_contracts/v2/client.py": "".join(py_client),
        ROOT / "packages/python-contracts/src/tool_defect_contracts/v2/__init__.py": py_init,
        ROOT / "packages/java-contracts/src/main/java/local/tooldefect/contracts/v2/ContractEnumsV2.java": "".join(java_enums),
        ROOT / "packages/java-contracts/src/main/java/local/tooldefect/contracts/v2/ApiClientV2.java": "".join(java_client),
        ROOT / "packages/java-contracts/src/main/java/local/tooldefect/contracts/v2/ContractModelsV2.java": java_models,
        ROOT / "packages/typescript-contracts/src/v2/index.ts": "".join(ts_index),
        ROOT / "packages/typescript-contracts/src/v2/client.ts": "".join(ts_client),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-deterministic", action="store_true")
    args = parser.parse_args()
    first = generated_files()
    if args.check_deterministic and first != generated_files():
        print("生成器非确定性", file=sys.stderr)
        return 1
    if args.check or args.check_deterministic:
        drift = [
            path.relative_to(ROOT).as_posix()
            for path, content in first.items()
            if not path.exists() or path.read_text(encoding="utf-8") != content
        ]
        if drift:
            print("检测到生成物漂移：", file=sys.stderr)
            for path in drift:
                print(f"- {path}", file=sys.stderr)
            return 1
        print("三语言生成物与契约一致且生成确定")
        return 0
    for path, content in first.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"已确定性生成 {len(first)} 个源文件；源哈希 {source_hash()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
