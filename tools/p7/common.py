"""P7 验证器共享的只读、安全失败工具。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any


SHA256 = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER = re.compile(
    r"(?:PENDING|PLACEHOLDER|TEMPLATE|EXAMPLE|SAMPLE|TBD|TODO|待填写|待签|待确认|示例|占位)",
    re.IGNORECASE,
)


@dataclass
class ValidationResult:
    """区分验证通过、外部前置阻塞和实现/输入错误。"""

    validator: str
    blockers: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.errors:
            return "ERROR"
        if self.blockers:
            return "BLOCKED"
        return "PASS"

    @property
    def exit_code(self) -> int:
        if self.errors:
            return 1
        if self.blockers:
            return 2
        return 0

    def block(self, message: str) -> None:
        if message not in self.blockers:
            self.blockers.append(message)

    def error(self, message: str) -> None:
        if message not in self.errors:
            self.errors.append(message)

    def merge(self, other: "ValidationResult", prefix: str | None = None) -> None:
        label = f"{prefix}:" if prefix else ""
        for message in other.blockers:
            self.block(f"{label}{message}")
        for message in other.errors:
            self.error(f"{label}{message}")
        self.checks[prefix or other.validator] = other.as_dict(include_checks=False)

    def as_dict(self, *, include_checks: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "validator": self.validator,
            "status": self.status,
            "blocker_count": len(self.blockers),
            "error_count": len(self.errors),
            "blockers": self.blockers[:200],
            "errors": self.errors[:200],
        }
        if include_checks:
            payload["checks"] = self.checks
        return payload

    def emit(self) -> int:
        print(
            json.dumps(
                self.as_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return self.exit_code


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"重复 JSON 字段：{key}")
        result[key] = value
    return result


def read_json_object(
    path: Path,
    result: ValidationResult,
    label: str,
    *,
    required: bool = True,
) -> dict[str, Any]:
    if not path.is_file():
        if required:
            result.block(f"{label}_missing:{path}")
        return {}
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ValueError(f"非有限 JSON 常量：{constant}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        result.error(f"{label}_invalid:{type(exc).__name__}:{path}")
        return {}
    if not isinstance(value, dict):
        result.error(f"{label}_root_not_object:{path}")
        return {}
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        return (
            not stripped
            or PLACEHOLDER.search(stripped) is not None
            or (stripped.startswith("<") and stripped.endswith(">"))
            or (stripped.startswith("${") and stripped.endswith("}"))
        )
    return False


def valid_iso8601(value: Any) -> bool:
    if not isinstance(value, str) or is_placeholder(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def get_dotted(value: dict[str, Any], dotted_key: str) -> tuple[bool, Any]:
    current: Any = value
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def resolve_evidence_path(value: Any, base: Path) -> Path | None:
    if not isinstance(value, str) or is_placeholder(value):
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        return candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def verify_file_evidence(
    *,
    path_value: Any,
    hash_value: Any,
    base: Path,
    result: ValidationResult,
    label: str,
) -> Path | None:
    path = resolve_evidence_path(path_value, base)
    if path is None or not path.is_file():
        result.block(f"{label}_file_missing")
        return None
    if not isinstance(hash_value, str) or SHA256.fullmatch(hash_value) is None:
        result.block(f"{label}_sha256_invalid")
        return None
    try:
        actual = sha256_file(path)
    except OSError as exc:
        result.error(f"{label}_unreadable:{type(exc).__name__}")
        return None
    if actual != hash_value:
        result.block(f"{label}_sha256_mismatch")
        return None
    return path


def _strip_yaml_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote == '"':
            escaped = True
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            continue
        if character == "#" and quote is None:
            return line[:index]
    return line


def _parse_yaml_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        raise ValueError("空标量")
    if value.startswith(("&", "*", "!", "|", ">", "[", "{")):
        raise ValueError("不允许 YAML 锚点、标签或复合标量")
    if value[0] in {"'", '"'}:
        if value[0] == '"':
            parsed = json.loads(value)
        elif len(value) >= 2 and value[-1] == "'":
            parsed = value[1:-1].replace("''", "'")
        else:
            raise ValueError("字符串引号未闭合")
        if not isinstance(parsed, str):
            raise ValueError("引号标量必须为字符串")
        return parsed
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    if re.fullmatch(r"[-+]?(?:0|[1-9]\d*)", value):
        return int(value)
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][-+]?\d+)?", value):
        return float(value)
    return value


def read_simple_yaml_mapping(
    path: Path,
    result: ValidationResult,
    label: str,
) -> dict[str, Any]:
    """解析本项目生产配置使用的安全 YAML 映射子集。

    为保持离线门禁不依赖可选 PyYAML，本解析器只接受空格缩进的嵌套映射
    与 JSON 兼容标量，并拒绝列表、锚点、标签和重复键。
    """

    if not path.is_file():
        result.block(f"{label}_missing:{path}")
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        result.error(f"{label}_unreadable:{type(exc).__name__}:{path}")
        return {}

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-2, root)]
    try:
        for line_number, original in enumerate(lines, start=1):
            if "\t" in original:
                raise ValueError(f"第 {line_number} 行包含制表符")
            line = _strip_yaml_comment(original).rstrip()
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent % 2:
                raise ValueError(f"第 {line_number} 行缩进必须为 2 的倍数")
            content = line.strip()
            if content.startswith("-"):
                raise ValueError(f"第 {line_number} 行不允许 YAML 列表")
            if ":" not in content:
                raise ValueError(f"第 {line_number} 行缺少键值分隔符")
            key, raw_value = content.split(":", 1)
            key = key.strip()
            if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$-]*", key) is None:
                raise ValueError(f"第 {line_number} 行键名非法：{key}")
            while stack and indent <= stack[-1][0]:
                stack.pop()
            if not stack or indent != stack[-1][0] + 2:
                raise ValueError(f"第 {line_number} 行缩进层级跳跃")
            parent = stack[-1][1]
            if key in parent:
                raise ValueError(f"第 {line_number} 行重复键：{key}")
            if not raw_value.strip():
                child: dict[str, Any] = {}
                parent[key] = child
                stack.append((indent, child))
            else:
                parent[key] = _parse_yaml_scalar(raw_value)
    except (ValueError, json.JSONDecodeError) as exc:
        result.error(f"{label}_invalid:{exc}")
        return {}
    return root


def read_env_file(
    path: Path,
    result: ValidationResult,
    label: str,
) -> dict[str, str]:
    if not path.is_file():
        result.block(f"{label}_missing:{path}")
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        result.error(f"{label}_unreadable:{type(exc).__name__}:{path}")
        return {}
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped.removeprefix("export ").lstrip()
        if "=" not in stripped:
            result.error(f"{label}_invalid_line:{line_number}")
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", key) is None:
            result.error(f"{label}_invalid_key:{line_number}:{key}")
            continue
        if key in values:
            result.error(f"{label}_duplicate_key:{key}")
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values
