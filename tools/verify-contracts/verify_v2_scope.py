#!/usr/bin/env python3
"""验证第二版未重新引入已取消的数据集或训练一等能力。"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
BANNED = {
    "datasetversion", "datasetapproval", "datasetdiff", "trainingrun", "trainingjob",
    "traininglog", "datasetcreate", "datasetapprove", "trainingstart", "/datasets", "/training-runs",
}


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9/]", "", value.lower())


def v2_contract_files() -> list[Path]:
    paths: list[Path] = []
    for directory in ("json-schema", "openapi", "asyncapi", "consumers"):
        paths.extend((CONTRACTS / directory).glob("*v2*.json"))
    paths.extend((CONTRACTS / "examples").rglob("*v2*.json"))
    return sorted(set(paths))


def walk(value: Any, path: Path, pointer: str = "") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = f"{pointer}/{key}"
            errors.extend(check_text(key, path, child_pointer, key_position=True))
            errors.extend(walk(child, path, child_pointer))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(walk(child, path, f"{pointer}/{index}"))
    elif isinstance(value, str):
        errors.extend(check_text(value, path, pointer, key_position=False))
    return errors


def check_text(value: str, path: Path, pointer: str, key_position: bool) -> list[str]:
    # 负向示例允许把被禁标识记录为待注入字段；第一版来源快照只允许通用枚举名称。
    if pointer.endswith("/invalid_field"):
        return []
    token = normalized(value)
    hits = sorted(item for item in BANNED if item in token)
    if not hits:
        return []
    return [f"{path.relative_to(ROOT)}{pointer}: 命中 {', '.join(hits)}"]


def generated_surface_errors() -> list[str]:
    paths = [
        ROOT / "packages/python-contracts/src/tool_defect_contracts/v2",
        ROOT / "packages/java-contracts/src/main/java/local/tooldefect/contracts/v2",
        ROOT / "packages/typescript-contracts/src/v2",
    ]
    errors: list[str] = []
    for directory in paths:
        if not directory.is_dir():
            errors.append(f"{directory.relative_to(ROOT)}: 第二版生成目录不存在")
            continue
        for path in sorted(file for file in directory.rglob("*") if file.is_file()):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                hits = sorted(item for item in BANNED if item in normalized(line))
                if hits:
                    errors.append(f"{path.relative_to(ROOT)}:{line_number}: 命中 {', '.join(hits)}")
    return errors


def consumer_surface_errors() -> list[str]:
    errors: list[str] = []
    roots = [ROOT / "apps", ROOT / "services", ROOT / "deploy"]
    suffixes = {".ts", ".tsx", ".js", ".java", ".py", ".json", ".yml", ".yaml"}
    for root in roots:
        if not root.exists():
            continue
        candidates: list[Path] = []
        for directory, names, files in os.walk(root):
            names[:] = [
                name for name in names
                if name not in {"node_modules", "target", "dist", "build", ".venv", "__pycache__", "coverage"}
            ]
            candidates.extend(
                Path(directory) / name
                for name in files
                if Path(name).suffix in suffixes
            )
        for path in sorted(candidates):
            text = path.read_text(encoding="utf-8", errors="replace")
            for line_number, line in enumerate(text.splitlines(), 1):
                # R1 尚未接入消费者；只把同一源码表面显式标为第二版的命中归给 v2。
                if "/api/v2" not in line and re.search(r"\bV2\b|contract[_-]?v2", line, re.I) is None:
                    continue
                hits = sorted(item for item in BANNED if item in normalized(line))
                if hits:
                    errors.append(f"{path.relative_to(ROOT)}:{line_number}: 命中 {', '.join(hits)}")
    return errors


def legacy_snapshot_errors(api: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if any("legacy" in path.lower() or "provenance" in path.lower() for path in api["paths"]):
        errors.append("第二版不得为历史来源快照提供独立路由")
    refs: list[str] = []
    def collect(value: Any, pointer: str = "") -> None:
        if isinstance(value, dict):
            if value.get("$ref", "").endswith("#/$defs/LegacyProvenanceSnapshot"):
                refs.append(pointer)
            for key, child in value.items():
                collect(child, f"{pointer}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                collect(child, f"{pointer}/{index}")
    collect(api)
    expected = ["/components/schemas/ModelHistoryItem/properties/legacy_provenance"]
    if refs != expected:
        errors.append(f"LegacyProvenanceSnapshot 只能嵌入模型历史只读响应，实际引用 {refs}")
    return errors


def validate_legacy_snapshot() -> list[str]:
    api = json.loads((CONTRACTS / "openapi" / "tool-defect-api-v2.json").read_text(encoding="utf-8"))
    return legacy_snapshot_errors(api)


def self_test() -> list[str]:
    errors: list[str] = []
    probe_path = CONTRACTS / "openapi" / "tool-defect-api-v2.json"
    if not check_text("TrainingRun", probe_path, "/probe", key_position=False):
        errors.append("范围门禁自测失败：未识别 TrainingRun")
    if check_text("training_run_id", probe_path, "/invalid_field", key_position=False):
        errors.append("范围门禁自测失败：负向样例豁免失效")
    api = json.loads(probe_path.read_text(encoding="utf-8"))
    damaged = copy.deepcopy(api)
    damaged["paths"]["/api/v2/legacy-provenance"] = {"get": {}}
    if not legacy_snapshot_errors(damaged):
        errors.append("范围门禁自测失败：未识别历史快照独立路由")
    damaged_ref = copy.deepcopy(api)
    damaged_ref["components"]["schemas"]["CreateBatchRequest"]["properties"]["legacy"] = {
        "$ref": "../json-schema/common-v2.schema.json#/$defs/LegacyProvenanceSnapshot"
    }
    if not legacy_snapshot_errors(damaged_ref):
        errors.append("范围门禁自测失败：未识别历史快照写请求滥用")
    return errors


def main() -> int:
    errors: list[str] = []
    for path in v2_contract_files():
        errors.extend(walk(json.loads(path.read_text(encoding="utf-8")), path))
    errors.extend(generated_surface_errors())
    errors.extend(consumer_surface_errors())
    errors.extend(validate_legacy_snapshot())
    errors.extend(self_test())
    if errors:
        print("第二版范围验证失败：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("第二版范围验证通过：取消清单、生成类型、消费者表面和历史快照边界均合规")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
