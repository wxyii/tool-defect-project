#!/usr/bin/env python3
"""从 01—14 号设计文档生成稳定、可反向验证的需求追踪矩阵。

需求编号由“文档编号 + 章节路径 + 规范化要求文本”的 SHA-256 派生。
未改变的要求即使移动行号也保持同一编号；要求语义被修改时会得到新编号，
从而避免旧测试静默覆盖新规则。
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import fnmatch
import hashlib
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = "1.0.0"
GENERATOR_VERSION = "1.0.0"

STRONG_MARKERS = (
    "必须",
    "不得",
    "禁止",
    "不能",
    "不允许",
    "严禁",
    "只允许",
    "只能",
    "不可",
    "至少",
    "应当",
    "务必",
    "默认拒绝",
    "需要",
    "验收",
)

STRONG_NEGATIVE_ACTIONS = (
    "不进入",
    "不写入",
    "不保存",
    "不覆盖",
    "不删除",
    "不依赖",
    "不访问",
    "不传输",
    "不展示",
    "不记录",
    "不暴露",
    "不直连",
    "不自行",
    "不默认",
    "不替代",
    "不修改",
    "不产生",
    "不使用",
    "不混用",
    "不执行",
    "不接受",
    "不信任",
)

SITE_KEYWORDS = {
    "DEC-CAPTURE-PLC-001": ("PLC", "传感器", "触发时序"),
    "DEC-CAPTURE-CAMERA-001": ("相机", "曝光", "图像质量"),
    "DEC-EDGE-OS-001": ("工控机", "驱动"),
    "DEC-PERFORMANCE-CYCLE-001": ("节拍",),
    "DEC-PERFORMANCE-LATENCY-001": ("延迟", "时延", "P95", "服务目标"),
    "DEC-OFFLINE-DURATION-001": ("离线", "断网", "网络中断"),
    "DEC-CAPACITY-LOCAL-DISK-001": ("磁盘", "容量", "水位"),
    "DEC-DISPOSITION-THRESHOLD-001": (
        "自动放行",
        "阈值",
        "自动 PASS",
        "自动 `PASS`",
    ),
    "DEC-DISPOSITION-SAMPLING-001": ("抽检",),
    "DEC-REVIEW-SLA-001": ("复核时限", "租约", "超时"),
    "DEC-RETENTION-001": ("保留期", "保留期限", "生命周期", "删除"),
    "DEC-RECOVERY-001": ("恢复", "备份", "高可用", "RPO", "RTO"),
    "DEC-IDENTITY-001": ("身份", "OIDC", "Keycloak"),
    "DEC-STORAGE-PRODUCT-001": ("对象存储", "SeaweedFS", "Ceph", "MinIO"),
    "DEC-MESSAGING-001": ("消息队列", "RabbitMQ"),
    "DEC-MONITORING-001": ("监控", "告警", "可观测"),
    "DEC-COMPUTE-001": ("CPU", "GPU", "服务器"),
    "DEC-DEPLOYMENT-001": ("部署平台", "Compose", "容器平台"),
    "DEC-DEPLOYMENT-K8S-001": ("Kubernetes",),
}

TEST_FILE_SUFFIXES = (
    ".py",
    ".java",
    ".kt",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
)

EXCLUDED_TEST_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "target",
    "build",
    "dist",
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def load_mapping(root: Path) -> dict[str, Any]:
    path = root / "Docs/traceability/mapping.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _clean_markdown(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text)
    if text.startswith("|") and text.endswith("|"):
        cells = [cell.strip() for cell in text.strip("|").split("|")]
        text = "；".join(cell for cell in cells if cell)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    return bool(
        stripped.startswith("|")
        and re.fullmatch(r"\|?[\s:|-]+\|?", stripped)
        and "-" in stripped
    )


def _is_normative(text: str, in_acceptance_section: bool) -> bool:
    if in_acceptance_section:
        return True
    return any(marker in text for marker in STRONG_MARKERS + STRONG_NEGATIVE_ACTIONS)


def _stable_requirement_id(
    document_number: str,
    section: str,
    text: str,
    occurrence: int,
) -> str:
    suffix = f"\n重复序号={occurrence}" if occurrence > 1 else ""
    digest = hashlib.sha256(
        f"{document_number}\n{section}\n{text}{suffix}".encode("utf-8")
    ).hexdigest()[:12].upper()
    return f"REQ-{document_number}-{digest}"


def _manual_reference(document_number: str, section: str) -> str:
    digest = hashlib.sha256(section.encode("utf-8")).hexdigest()[:8].upper()
    return f"MANUAL-{document_number}-{digest}"


def _site_decisions(text: str, valid_ids: set[str]) -> list[str]:
    matches = []
    for decision_id, keywords in SITE_KEYWORDS.items():
        if decision_id in valid_ids and any(keyword in text for keyword in keywords):
            matches.append(decision_id)
    return sorted(matches)


def extract_requirements(
    root: Path,
    mapping: dict[str, Any],
    decision_ids: set[str],
) -> list[dict[str, Any]]:
    requirements: list[dict[str, Any]] = []
    duplicate_counts: Counter[tuple[str, str, str]] = Counter()
    for document_number, policy in sorted(mapping["documents"].items()):
        relative_path = policy["path"]
        path = root / relative_path
        lines = path.read_text(encoding="utf-8").splitlines()
        headings: list[tuple[int, str]] = []
        in_code_fence = False

        for index, raw_line in enumerate(lines):
            line_number = index + 1
            stripped = raw_line.strip()
            if stripped.startswith("```"):
                in_code_fence = not in_code_fence
                continue
            if in_code_fence or not stripped:
                continue

            heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                title = _clean_markdown(heading_match.group(2))
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, title))
                continue

            if _is_table_separator(stripped):
                continue
            if (
                stripped.startswith("|")
                and index + 1 < len(lines)
                and _is_table_separator(lines[index + 1])
            ):
                continue

            section = " > ".join(title for _, title in headings) or "文档正文"
            in_acceptance = any(
                "验收" in title or "检查清单" in title
                for _, title in headings
            )
            text = _clean_markdown(stripped)
            if not text or not _is_normative(text, in_acceptance):
                continue

            duplicate_key = (document_number, section, text)
            duplicate_counts[duplicate_key] += 1
            requirement_id = _stable_requirement_id(
                document_number,
                section,
                text,
                duplicate_counts[duplicate_key],
            )
            decisions = _site_decisions(f"{section} {text}", decision_ids)
            manual_refs = (
                [_manual_reference(document_number, section)]
                if in_acceptance
                else []
            )
            tasks = list(policy["tasks"])
            gates = list(policy["gates"])
            if decisions:
                verification_kind = "现场决策"
                verification_refs = decisions
            elif manual_refs:
                verification_kind = "人工验收"
                verification_refs = manual_refs
            else:
                verification_kind = "任务自动化验证"
                verification_refs = [f"TASK-TEST:{tasks[0]}"]

            go_live = any(
                keyword in f"{section} {text}"
                for keyword in (
                    "上线",
                    "生产",
                    "发布",
                    "真实",
                    "现场",
                    "签字",
                    "验收",
                )
            )
            requirements.append(
                {
                    "id": requirement_id,
                    "source": {
                        "document": relative_path,
                        "line": line_number,
                        "section": section,
                    },
                    "text": text,
                    "tasks": tasks,
                    "gates": gates,
                    "verification_kind": verification_kind,
                    "verification_refs": verification_refs,
                    "go_live_prerequisite": go_live,
                    "automated_tests": [],
                }
            )
    return requirements


def _is_test_source(path: Path) -> bool:
    if path.suffix.lower() not in TEST_FILE_SUFFIXES:
        return False
    name = path.name.lower()
    return bool(
        name.startswith("test_")
        or name.endswith("test.java")
        or name.endswith("tests.java")
        or ".test." in name
        or ".spec." in name
    )


def _python_test_ids(root: Path, path: Path) -> list[str]:
    relative = path.relative_to(root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return [f"{relative}::<无法解析>"]
    result = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test_"
        ):
            result.append(f"{relative}::{node.name}")
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(
                    child,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                ) and child.name.startswith("test_"):
                    result.append(f"{relative}::{node.name}.{child.name}")
    return result or [f"{relative}::<文件级测试>"]


def _other_test_ids(root: Path, path: Path) -> list[str]:
    relative = path.relative_to(root).as_posix()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return [f"{relative}::<文件级测试>"]
    identifiers = []
    patterns = (
        re.compile(r"\b(?:test|it)\s*\(\s*['\"]([^'\"]+)['\"]"),
        re.compile(r"\b(?:void|fun)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    )
    for line_number, line in enumerate(lines, start=1):
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                identifiers.append(
                    f"{relative}::{match.group(1)}@{line_number}"
                )
                break
    return identifiers or [f"{relative}::<文件级测试>"]


def discover_tests(root: Path) -> list[dict[str, str]]:
    tests = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _is_test_source(path):
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_TEST_PARTS for part in relative.parts):
            continue
        identifiers = (
            _python_test_ids(root, path)
            if path.suffix.lower() == ".py"
            else _other_test_ids(root, path)
        )
        tests.extend(
            {"id": identifier, "path": relative.as_posix()}
            for identifier in identifiers
        )
    return tests


def _select_requirement(
    requirements: list[dict[str, Any]],
    documents: list[str],
    keywords: list[str],
) -> str:
    candidates = [
        requirement
        for requirement in requirements
        if requirement["id"].split("-")[1] in documents
    ]
    if not candidates:
        raise ValueError(f"测试映射找不到文档要求：{documents}")
    scored = []
    for requirement in candidates:
        haystack = (
            requirement["source"]["section"] + " " + requirement["text"]
        )
        score = sum(1 for keyword in keywords if keyword in haystack)
        scored.append((score, requirement["id"]))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][1]


def build_test_links(
    root: Path,
    mapping: dict[str, Any],
    requirements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rules = mapping["test_mappings"]
    links = []
    for test in discover_tests(root):
        relative = test["path"]
        rule = next(
            (
                item
                for item in rules
                if fnmatch.fnmatch(relative, item["pattern"])
            ),
            None,
        )
        if rule is None:
            raise ValueError(f"测试没有反向映射规则：{relative}")
        requirement_id = _select_requirement(
            requirements,
            rule["documents"],
            rule.get("keywords", []),
        )
        links.append(
            {
                "test_id": test["id"],
                "requirement_ids": [requirement_id],
                "mapping_rule": rule["pattern"],
            }
        )
    links.sort(key=lambda item: item["test_id"])
    return links


def _attach_tests(
    requirements: list[dict[str, Any]],
    test_links: list[dict[str, Any]],
) -> None:
    by_id = {item["id"]: item for item in requirements}
    for link in test_links:
        for requirement_id in link["requirement_ids"]:
            by_id[requirement_id]["automated_tests"].append(link["test_id"])
    for requirement in requirements:
        requirement["automated_tests"].sort()


def build_matrix(root: Path, include_tests: bool = True) -> dict[str, Any]:
    root = root.resolve()
    mapping = load_mapping(root)
    registry_path = root / "Docs/decisions/site-parameter-decisions.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    decision_ids = {item["id"] for item in registry["decisions"]}
    requirements = extract_requirements(root, mapping, decision_ids)
    test_links = (
        build_test_links(root, mapping, requirements) if include_tests else []
    )
    if include_tests:
        _attach_tests(requirements, test_links)

    document_summary = {}
    for document_number, policy in sorted(mapping["documents"].items()):
        document_requirements = [
            item
            for item in requirements
            if item["id"].split("-")[1] == document_number
        ]
        document_summary[document_number] = {
            "path": policy["path"],
            "source_sha256": sha256_file(root / policy["path"]),
            "requirement_count": len(document_requirements),
            "requirement_ids_sha256": canonical_sha256(
                [item["id"] for item in document_requirements]
            ),
        }

    stable_requirements = [
        {key: value for key, value in item.items() if key != "automated_tests"}
        for item in requirements
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "requirement_count": len(requirements),
        "documents": document_summary,
        "requirements": requirements,
        "test_links": test_links,
        "stable_requirements_sha256": canonical_sha256(stable_requirements),
    }


def build_lock(matrix: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "requirement_count": matrix["requirement_count"],
        "documents": matrix["documents"],
        "stable_requirements_sha256": matrix["stable_requirements_sha256"],
    }


def validate_matrix(
    root: Path,
    matrix: dict[str, Any],
    lock: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    requirements = matrix["requirements"]
    identifiers = [item["id"] for item in requirements]
    if len(identifiers) != len(set(identifiers)):
        errors.append("稳定需求编号存在重复")
    if set(matrix["documents"]) != {f"{number:02d}" for number in range(1, 15)}:
        errors.append("设计文档覆盖不是完整的 01—14")

    for document_number, summary in matrix["documents"].items():
        if summary["requirement_count"] == 0:
            errors.append(f"文档 {document_number} 没有强制要求")

    valid_ids = set(identifiers)
    for requirement in requirements:
        source = requirement["source"]
        source_path = root / source["document"]
        if not source_path.is_file():
            errors.append(f"{requirement['id']} 来源文档不存在")
        if not requirement["tasks"]:
            errors.append(f"{requirement['id']} 没有归属任务")
        if not requirement["gates"]:
            errors.append(f"{requirement['id']} 没有门禁")
        if requirement["go_live_prerequisite"] and not requirement["gates"]:
            errors.append(f"{requirement['id']} 上线前置要求没有门禁")
        if not requirement["verification_refs"]:
            errors.append(f"{requirement['id']} 没有验证、人工或现场映射")

    linked_tests = set()
    for link in matrix["test_links"]:
        linked_tests.add(link["test_id"])
        for requirement_id in link["requirement_ids"]:
            if requirement_id not in valid_ids:
                errors.append(
                    f"{link['test_id']} 指向未知需求 {requirement_id}"
                )
    discovered_tests = {item["id"] for item in discover_tests(root)}
    missing_test_links = sorted(discovered_tests - linked_tests)
    if missing_test_links:
        errors.append("测试没有反向需求：" + ", ".join(missing_test_links))

    regenerated = build_matrix(root, include_tests=True)
    if matrix != regenerated:
        errors.append("矩阵不是当前来源文档的确定性生成结果")

    if lock is not None and build_lock(matrix) != lock:
        errors.append("需求矩阵与冻结摘要不一致")
    return errors


def _summary(matrix: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": matrix["schema_version"],
        "generator_version": matrix["generator_version"],
        "requirement_count": matrix["requirement_count"],
        "test_count": len(matrix["test_links"]),
        "documents": matrix["documents"],
        "stable_requirements_sha256": matrix["stable_requirements_sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repository_root(),
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="只输出文档计数、摘要和测试数量。",
    )
    parser.add_argument(
        "--without-tests",
        action="store_true",
        help="不扫描测试反向链接。",
    )
    parser.add_argument(
        "--verify-lock",
        type=Path,
        help="验证冻结摘要。",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="输出紧凑 JSON。",
    )
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    matrix = build_matrix(root, include_tests=not args.without_tests)
    errors = []
    if args.verify_lock:
        lock = json.loads(args.verify_lock.read_text(encoding="utf-8"))
        errors = validate_matrix(root, matrix, lock)
        payload: dict[str, Any] = {
            "valid": not errors,
            "errors": errors,
            **_summary(matrix),
        }
    else:
        payload = _summary(matrix) if args.summary else matrix
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=None if args.compact else 2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
