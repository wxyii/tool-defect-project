#!/usr/bin/env python3
"""从 v1 契约确定性生成 Python、Java 与 TypeScript 类型及客户端表面。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def source_hash() -> str:
    digest = hashlib.sha256()
    paths = []
    for directory in ("json-schema", "openapi", "asyncapi"):
        paths.extend((CONTRACTS / directory).glob("*.json"))
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
    common = load(CONTRACTS / "json-schema" / "common-v1.schema.json")
    enums = {
        name: definition["enum"]
        for name, definition in common["$defs"].items()
        if "enum" in definition
    }
    api = load(CONTRACTS / "openapi" / "tool-defect-api-v1.json")
    operations = sorted(
        operation["operationId"]
        for item in api["paths"].values()
        for method, operation in item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    )
    return enums, operations, source_hash()


def snake_upper(value: str) -> str:
    return value.replace("-", "_").replace("/", "_").upper()


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

    ts_models = [
        ts_header,
        f'export const CONTRACT_SOURCE_SHA256 = "{digest}" as const;\n',
        "export const CONTRACT_MAJOR_VERSION = 1 as const;\n\n",
    ]
    for name, values in sorted(enums.items()):
        union = " | ".join(json.dumps(value) for value in values)
        ts_models.append(f"export type {name} = {union};\n")
    ts_models.extend(
        [
            "\nexport interface ObjectReference {\n",
            "  readonly bucket: string;\n",
            "  readonly object_key: string;\n",
            "  readonly sha256: string;\n",
            "  readonly size_bytes: number;\n",
            "  readonly media_type: string;\n",
            "  readonly object_version?: string | null;\n",
            "}\n",
        ]
    )
    ts_client = [
        ts_header,
        "export type JsonObject = Readonly<Record<string, unknown>>;\n\n",
        "export interface ApiClient {\n",
    ]
    for operation in operations:
        ts_client.append(
            f"  {operation}(request?: JsonObject): Promise<JsonObject>;\n"
        )
    ts_client.append("}\n")

    return {
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
        ROOT / "packages/typescript-contracts/src/client.ts": "".join(ts_client),
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
