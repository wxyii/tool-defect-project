#!/usr/bin/env python3
"""从精确依赖声明和固定容器镜像生成 CycloneDX 1.6 软件物料清单。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def component(kind: str, name: str, version: str, purl: str) -> dict[str, Any]:
    return {
        "type": kind,
        "name": name,
        "version": version,
        "purl": purl,
        "bom-ref": purl,
    }


def exact_python_dependencies(errors: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted((ROOT / "requirements").glob("*.lock")):
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line)
            if not match:
                errors.append(f"{path.relative_to(ROOT)}:{number} 不是精确 == 锁")
                continue
            name, version = match.groups()
            normalized = name.lower().replace("_", "-")
            result.append(
                component(
                    "library",
                    name,
                    version,
                    f"pkg:pypi/{normalized}@{version}",
                )
            )
    for path in (
        ROOT / "apps/edge-agent/pyproject.toml",
        ROOT / "services/inference-service/pyproject.toml",
        ROOT / "packages/python-contracts/pyproject.toml",
    ):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for dependency in data.get("build-system", {}).get("requires", []):
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", dependency)
            if not match:
                errors.append(f"{path.relative_to(ROOT)} 含非精确构建依赖 {dependency}")
                continue
            name, version = match.groups()
            result.append(
                component(
                    "library",
                    name,
                    version,
                    f"pkg:pypi/{name.lower().replace('_', '-')}@{version}",
                )
            )
        for dependency in data.get("project", {}).get("dependencies", []):
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", dependency)
            if not match:
                errors.append(f"{path.relative_to(ROOT)} 含非精确运行时依赖 {dependency}")
    return result


def maven_components(errors: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    namespace = {"m": "http://maven.apache.org/POM/4.0.0"}
    for path in (
        ROOT / "services/business-api/pom.xml",
        ROOT / "packages/java-contracts/pom.xml",
    ):
        root = ET.parse(path).getroot()
        properties_node = root.find("m:properties", namespace)
        properties = (
            {
                child.tag.rsplit("}", 1)[-1]: (child.text or "").strip()
                for child in properties_node
            }
            if properties_node is not None
            else {}
        )
        for node in root.findall(".//m:dependency", namespace) + root.findall(
            ".//m:plugin", namespace
        ):
            group = node.findtext("m:groupId", namespaces=namespace)
            artifact = node.findtext("m:artifactId", namespaces=namespace)
            version = node.findtext("m:version", namespaces=namespace)
            if version:
                property_match = re.fullmatch(r"\$\{([^}]+)\}", version)
                if property_match:
                    version = properties.get(property_match.group(1))
            if not group or not artifact or not version or "${" in version:
                errors.append(f"{path.relative_to(ROOT)} 的 {artifact or '依赖'} 未固定版本")
                continue
            result.append(
                component(
                    "library",
                    artifact,
                    version,
                    f"pkg:maven/{group}/{artifact}@{version}",
                )
            )
    return result


def node_components(errors: list[str]) -> list[dict[str, Any]]:
    path = ROOT / "packages/typescript-contracts/package.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("engines", {}).get("node") != "20.13.1":
        errors.append(f"{path.relative_to(ROOT)} 未精确锁定 Node.js 20.13.1")
    if data.get("packageManager") != "pnpm@10.34.5":
        errors.append(f"{path.relative_to(ROOT)} 未精确锁定 pnpm 10.34.5")
    result = []
    for section in ("dependencies", "devDependencies"):
        for name, version in data.get(section, {}).items():
            if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version):
                errors.append(f"{path.relative_to(ROOT)} 的 {name} 未固定版本")
                continue
            encoded = name.replace("@", "%40").replace("/", "%2F")
            result.append(component("library", name, version, f"pkg:npm/{encoded}@{version}"))
    return result


def container_components(errors: list[str]) -> list[dict[str, Any]]:
    text = (ROOT / "deploy/compose/development.yml").read_text(encoding="utf-8")
    result = []
    for image in re.findall(r"(?m)^\s+image:\s*(\S+)\s*$", text):
        final = image.rsplit("/", 1)[-1]
        if ":" not in final or final.endswith(":latest"):
            errors.append(f"容器镜像未固定：{image}")
            continue
        name, version = image.rsplit(":", 1)
        result.append(component("container", name, version, f"pkg:oci/{name}@{version}"))
    return result


def build_bom() -> dict[str, Any]:
    errors: list[str] = []
    components = (
        exact_python_dependencies(errors)
        + maven_components(errors)
        + node_components(errors)
        + container_components(errors)
    )
    unique = {item["bom-ref"]: item for item in components}
    if "pkg:pypi/cryptography@49.0.0" not in unique:
        errors.append("软件物料清单缺少 cryptography 49.0.0")
    if errors:
        raise ValueError("；".join(errors))
    ordered = [unique[key] for key in sorted(unique)]
    fingerprint = hashlib.sha256(
        json.dumps(ordered, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{fingerprint[:8]}-{fingerprint[8:12]}-{fingerprint[12:16]}-{fingerprint[16:20]}-{fingerprint[20:32]}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "tool-defect-project",
                "version": "1.0.0",
            },
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "tools/sbom/generate_sbom.py",
                        "version": "1",
                    }
                ]
            },
        },
        "components": ordered,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        first = build_bom()
        if first != build_bom():
            raise ValueError("软件物料清单生成不确定")
    except (ValueError, ET.ParseError) as exc:
        print(f"软件物料清单生成失败：{exc}", file=sys.stderr)
        return 1
    if args.check:
        with tempfile.TemporaryDirectory(prefix="sbom-") as directory:
            path = Path(directory) / "p1.cdx.json"
            path.write_text(
                json.dumps(first, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            json.loads(path.read_text(encoding="utf-8"))
        print(f"软件物料清单检查通过：{len(first['components'])} 个唯一组件")
        return 0
    output = args.output or ROOT / ".build/reports/p1.cdx.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(first, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"已生成软件物料清单：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
