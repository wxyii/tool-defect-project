"""不可变模型包的严格解析、哈希与数字签名验证。"""

from base64 import b64decode
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from tool_defect.plugin_api import PluginError, PluginErrorCode


REQUIRED_PACKAGE_FILES = frozenset(
    {
        "manifest.json",
        "model.json",
        "weights.h5",
        "labels.json",
        "preprocessing.json",
        "metrics.json",
        "environment.lock",
        "checksums.sha256",
        "signature.sig",
    }
)
CHECKSUMMED_FILES = REQUIRED_PACKAGE_FILES.difference(
    {"checksums.sha256", "signature.sig"}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONFIG_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_PLUGIN_VERSION = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_ALLOWED_OPTIONAL_FILES = {"warmup-input.npy", "warmup-expected.json"}
_FORBIDDEN_SUFFIXES = {
    ".py",
    ".pyc",
    ".pyd",
    ".so",
    ".dll",
    ".dylib",
    ".sh",
    ".bat",
    ".ps1",
}


@dataclass(frozen=True)
class ModelInputSpec:
    shape: tuple[int, ...]
    dtype: str
    color_space: str
    value_range: tuple[float, float]


@dataclass(frozen=True)
class PreprocessorRequirement:
    plugin_id: str
    plugin_version: str
    config_sha256: str


@dataclass(frozen=True)
class ModelManifest:
    model_name: str
    model_version: str
    framework: str
    framework_version: str
    keras_version: str
    python_version: str
    input_spec: ModelInputSpec
    output_names: tuple[str, ...]
    label_map: Mapping[int, str]
    preprocessor: PreprocessorRequirement
    dataset_version: str
    source_run_id: str


@dataclass(frozen=True)
class ApprovedArtifact:
    model_name: str
    model_version: str
    package_sha256: str
    signer_key_id: str
    approval_state: str


@dataclass(frozen=True)
class VerifiedModelPackage:
    root: Path
    manifest: ModelManifest
    package_sha256: str
    file_sha256: Mapping[str, str]
    signer_key_id: str
    verification_report: Mapping[str, Any]


class SignatureVerifier(Protocol):
    def verify(
        self,
        key_id: str,
        payload: bytes,
        signature: bytes,
        algorithm: str,
    ) -> None:
        ...


class Ed25519SignatureVerifier:
    """使用受信 Ed25519 公钥验证离线模型包签名。"""

    def __init__(self, trusted_public_keys: Mapping[str, bytes]):
        self._keys = dict(trusted_public_keys)

    def verify(
        self,
        key_id: str,
        payload: bytes,
        signature: bytes,
        algorithm: str,
    ) -> None:
        if algorithm != "ed25519":
            raise ValueError(f"不支持的模型签名算法：{algorithm}")
        if key_id not in self._keys:
            raise ValueError(f"未知模型签名密钥：{key_id}")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        key = Ed25519PublicKey.from_public_bytes(self._keys[key_id])
        key.verify(signature, payload)


class ModelPackageVerifier:
    def __init__(
        self,
        signature_verifier: SignatureVerifier,
        *,
        allowed_frameworks: tuple[str, ...] = ("tensorflow",),
        allowed_framework_versions: tuple[str, ...] = ("2.13.0",),
        allowed_keras_versions: tuple[str, ...] = ("2.13.1",),
        allowed_python_versions: tuple[str, ...] = ("3.11",),
        maximum_package_bytes: int = 8 * 1024 * 1024 * 1024,
    ):
        self._signature_verifier = signature_verifier
        self._allowed_frameworks = set(allowed_frameworks)
        self._allowed_framework_versions = set(
            allowed_framework_versions
        )
        self._allowed_keras_versions = set(allowed_keras_versions)
        self._allowed_python_versions = set(allowed_python_versions)
        self._maximum_package_bytes = int(maximum_package_bytes)
        if self._maximum_package_bytes <= 0:
            raise ValueError("模型包大小限制必须为正数")

    def verify(
        self,
        package_root: Path,
        approved: ApprovedArtifact,
    ) -> VerifiedModelPackage:
        requested_root = Path(package_root)
        if requested_root.is_symlink():
            raise _incompatible("模型包根目录不能是符号链接")
        try:
            root = requested_root.resolve(strict=True)
        except FileNotFoundError as error:
            raise _incompatible("模型包目录不存在") from error
        if not root.is_dir():
            raise _incompatible("模型包路径不是目录")
        discovered = _discover_files(root)
        missing = REQUIRED_PACKAGE_FILES.difference(discovered)
        if missing:
            raise _incompatible(
                "模型包缺少必需文件",
                {"missing": sorted(missing)},
            )
        allowed = REQUIRED_PACKAGE_FILES.union(_ALLOWED_OPTIONAL_FILES)
        unexpected = set(discovered).difference(allowed)
        if unexpected:
            raise _incompatible(
                "模型包包含未声明文件",
                {"unexpected": sorted(unexpected)},
            )
        total_bytes = sum(
            path.stat().st_size for path in discovered.values()
        )
        if total_bytes > self._maximum_package_bytes:
            raise _incompatible(
                "模型包总大小超过限制",
                {
                    "actual_bytes": total_bytes,
                    "maximum_bytes": self._maximum_package_bytes,
                },
            )
        manifest = parse_manifest(_load_json(root / "manifest.json"))
        labels = _parse_labels(_load_json(root / "labels.json"))
        preprocessing = _load_json(root / "preprocessing.json")
        _load_json(root / "metrics.json")
        if labels != dict(manifest.label_map):
            raise _incompatible("labels.json 与模型清单类别映射不一致")
        _verify_preprocessing(manifest, preprocessing)
        if manifest.framework not in self._allowed_frameworks:
            raise _incompatible("模型框架不在允许列表")
        if manifest.framework_version not in self._allowed_framework_versions:
            raise _incompatible(
                "模型框架版本不在允许列表",
                {"framework_version": manifest.framework_version},
            )
        if manifest.keras_version not in self._allowed_keras_versions:
            raise _incompatible(
                "Keras 版本不在允许列表",
                {"keras_version": manifest.keras_version},
            )
        if manifest.python_version not in self._allowed_python_versions:
            raise _incompatible("模型 Python 版本不在允许列表")
        if not (root / "environment.lock").read_bytes():
            raise _incompatible("模型环境锁不能为空")
        warmup_files = {
            name
            for name in _ALLOWED_OPTIONAL_FILES
            if name in discovered
        }
        if warmup_files and warmup_files != _ALLOWED_OPTIONAL_FILES:
            raise _incompatible(
                "固定预热输入和期望结果必须成对提供",
                {"present": sorted(warmup_files)},
            )

        checksum_payload = (root / "checksums.sha256").read_bytes()
        checksums = _parse_checksums(checksum_payload)
        expected_checksummed = CHECKSUMMED_FILES.union(
            set(discovered).intersection(_ALLOWED_OPTIONAL_FILES)
        )
        if set(checksums) != expected_checksummed:
            raise _incompatible(
                "哈希清单文件集合与模型包不一致",
                {
                    "expected": sorted(expected_checksummed),
                    "actual": sorted(checksums),
                },
            )
        for relative, expected_sha256 in checksums.items():
            actual = file_sha256(root / relative)
            if actual != expected_sha256:
                raise _incompatible(
                    "模型包文件哈希不匹配",
                    {
                        "file": relative,
                        "expected": expected_sha256,
                        "actual": actual,
                    },
                )

        signature_payload = _load_json(root / "signature.sig")
        signature_fields = {"algorithm", "key_id", "signature_base64"}
        if set(signature_payload) != signature_fields:
            raise _incompatible("模型签名字段不完整或包含未知字段")
        if any(
            not isinstance(signature_payload[name], str)
            or not signature_payload[name]
            for name in signature_fields
        ):
            raise _incompatible("模型签名字段必须是非空字符串")
        try:
            signature = b64decode(
                signature_payload["signature_base64"], validate=True
            )
            self._signature_verifier.verify(
                signature_payload["key_id"],
                checksum_payload,
                signature,
                signature_payload["algorithm"],
            )
        except Exception as error:
            raise _incompatible(
                "模型包数字签名验证失败",
                {"exception_type": type(error).__name__},
            ) from error

        package_sha256 = hashlib.sha256(checksum_payload).hexdigest()
        _verify_approval(
            manifest,
            package_sha256,
            signature_payload["key_id"],
            approved,
        )
        report = {
            "status": "VERIFIED",
            "model_name": manifest.model_name,
            "model_version": manifest.model_version,
            "package_sha256": package_sha256,
            "signer_key_id": signature_payload["key_id"],
            "verified_files": sorted(checksums),
        }
        return VerifiedModelPackage(
            root=root,
            manifest=manifest,
            package_sha256=package_sha256,
            file_sha256=MappingProxyType(dict(checksums)),
            signer_key_id=signature_payload["key_id"],
            verification_report=MappingProxyType(report),
        )


def parse_manifest(payload: Mapping[str, Any]) -> ModelManifest:
    if not isinstance(payload, Mapping):
        raise _incompatible("模型清单顶层必须是对象")
    required = {
        "model_name",
        "model_version",
        "framework",
        "framework_version",
        "keras_version",
        "python_version",
        "input_spec",
        "output_names",
        "label_map",
        "preprocessor",
        "dataset_version",
        "source_run_id",
    }
    if set(payload) != required:
        raise _incompatible(
            "模型清单字段不完整或包含未知字段",
            {
                "missing": sorted(required.difference(payload)),
                "unknown": sorted(set(payload).difference(required)),
            },
        )
    input_payload = payload["input_spec"]
    if not isinstance(input_payload, Mapping):
        raise _incompatible("模型输入规范必须是对象")
    if set(input_payload) != {"shape", "dtype", "color_space", "range"}:
        raise _incompatible("模型输入规范字段非法")
    if not isinstance(input_payload["shape"], list):
        raise _incompatible("模型输入形状必须是数组")
    try:
        shape = tuple(int(value) for value in input_payload["shape"])
    except (TypeError, ValueError) as error:
        raise _incompatible("模型输入形状包含非法值") from error
    if len(shape) != 3 or any(value <= 0 for value in shape):
        raise _incompatible("模型输入形状必须是正数 H x W x C")
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in input_payload["shape"]
    ):
        raise _incompatible("模型输入形状只能包含整数")
    if shape[2] != 3 or shape[0] * shape[1] > 40_000_000:
        raise _incompatible("模型输入必须是三通道且像素数不超过限制")
    if not isinstance(input_payload["range"], list):
        raise _incompatible("模型输入数值范围必须是数组")
    try:
        value_range = tuple(float(value) for value in input_payload["range"])
    except (TypeError, ValueError) as error:
        raise _incompatible("模型输入数值范围包含非法值") from error
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        for value in input_payload["range"]
    ):
        raise _incompatible("模型输入数值范围只能包含数值")
    if len(value_range) != 2 or value_range[0] >= value_range[1]:
        raise _incompatible("模型输入数值范围非法")
    if (
        input_payload["dtype"] != "float32"
        or input_payload["color_space"] != "RGB"
        or value_range != (0.0, 1.0)
    ):
        raise _incompatible(
            "当前模型输入规范必须为 float32 RGB 且范围 0 到 1"
        )
    preprocessor_payload = payload["preprocessor"]
    if not isinstance(preprocessor_payload, Mapping):
        raise _incompatible("模型预处理要求必须是对象")
    if set(preprocessor_payload) != {
        "plugin_id",
        "plugin_version",
        "config_hash",
    }:
        raise _incompatible("模型预处理要求字段非法")
    labels = _parse_labels(payload["label_map"])
    if labels != {0: "qualified", 1: "unqualified"}:
        raise _incompatible("当前模型类别映射必须为 0/1 合格与不合格")
    if not isinstance(payload["output_names"], list) or any(
        not isinstance(name, str) or not name
        for name in payload["output_names"]
    ):
        raise _incompatible("模型输出名必须是非空字符串数组")
    outputs = tuple(payload["output_names"])
    if not outputs or len(set(outputs)) != len(outputs):
        raise _incompatible("模型输出名不能为空或重复")
    string_names = (
        "model_name",
        "model_version",
        "framework",
        "framework_version",
        "keras_version",
        "python_version",
        "dataset_version",
        "source_run_id",
    )
    if any(
        not isinstance(payload[name], str) or not payload[name]
        for name in string_names
    ):
        raise _incompatible("模型清单字符串字段不能为空")
    strings = {name: payload[name] for name in string_names}
    plugin_id = preprocessor_payload["plugin_id"]
    plugin_version = preprocessor_payload["plugin_version"]
    config_hash = preprocessor_payload["config_hash"]
    if not isinstance(plugin_id, str) or not plugin_id.startswith(
        "tool-defect."
    ):
        raise _incompatible("模型预处理插件标识非法")
    if (
        not isinstance(plugin_version, str)
        or _PLUGIN_VERSION.fullmatch(plugin_version) is None
    ):
        raise _incompatible("模型预处理插件版本非法")
    if (
        not isinstance(config_hash, str)
        or _CONFIG_SHA256.fullmatch(config_hash) is None
    ):
        raise _incompatible("模型预处理配置哈希非法")
    return ModelManifest(
        **strings,
        input_spec=ModelInputSpec(
            shape=shape,
            dtype=str(input_payload["dtype"]),
            color_space=str(input_payload["color_space"]),
            value_range=value_range,
        ),
        output_names=outputs,
        label_map=MappingProxyType(labels),
        preprocessor=PreprocessorRequirement(
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            config_sha256=config_hash,
        ),
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def recheck_verified_package(
    package: VerifiedModelPackage,
) -> None:
    """在加载边界重查已验包对象及文件，缩小验签后的篡改窗口。"""

    if not isinstance(package, VerifiedModelPackage):
        raise _incompatible("模型加载只接受已验证模型包对象")
    report = package.verification_report
    if (
        report.get("status") != "VERIFIED"
        or report.get("model_name") != package.manifest.model_name
        or report.get("model_version") != package.manifest.model_version
        or report.get("package_sha256") != package.package_sha256
        or report.get("signer_key_id") != package.signer_key_id
    ):
        raise _incompatible("模型包验证报告与加载对象不一致")
    try:
        root = package.root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _incompatible("已验证模型包目录不可访问") from error
    if root != package.root or package.root.is_symlink():
        raise _incompatible("已验证模型包根目录发生变化")
    for relative, expected in package.file_sha256.items():
        if (
            not isinstance(relative, str)
            or "/" in relative
            or _SHA256.fullmatch(expected) is None
        ):
            raise _incompatible("已验证模型包文件清单非法")
        try:
            path = (root / relative).resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise _incompatible(
                "已验证模型包文件缺失", {"file": relative}
            ) from error
        if (
            path.parent != root
            or path.is_symlink()
            or not path.is_file()
            or file_sha256(path) != expected
        ):
            raise _incompatible(
                "模型包在验证后发生变化", {"file": relative}
            )
    checksum_path = root / "checksums.sha256"
    signature_path = root / "signature.sig"
    if (
        not checksum_path.is_file()
        or not signature_path.is_file()
        or hashlib.sha256(checksum_path.read_bytes()).hexdigest()
        != package.package_sha256
        or _parse_checksums(checksum_path.read_bytes())
        != dict(package.file_sha256)
    ):
        raise _incompatible("模型包校验和身份在验证后发生变化")


def _discover_files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise _incompatible("模型包不能包含符号链接")
        if path.is_dir():
            continue
        if not path.is_file():
            raise _incompatible(
                "模型包只能包含普通文件",
                {"file": path.relative_to(root).as_posix()},
            )
        relative = path.relative_to(root).as_posix()
        if "/" in relative:
            raise _incompatible(
                "首版模型包不允许嵌套文件", {"file": relative}
            )
        if path.suffix.lower() in _FORBIDDEN_SUFFIXES:
            raise _incompatible(
                "模型包不能包含可执行脚本或共享库", {"file": relative}
            )
        result[relative] = path
    return result


def _parse_checksums(payload: bytes) -> dict[str, str]:
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise _incompatible("哈希清单不是 UTF-8") from error
    result: dict[str, str] = {}
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or _SHA256.fullmatch(parts[0]) is None:
            raise _incompatible("哈希清单行格式非法")
        relative = parts[1]
        candidate = Path(relative)
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or candidate.as_posix() != relative
        ):
            raise _incompatible("哈希清单包含不安全路径")
        if relative in result:
            raise _incompatible("哈希清单包含重复文件")
        result[relative] = parts[0]
    return result


def _load_json(path: Path) -> dict[str, Any]:
    def reject_duplicate_pairs(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"重复字段：{key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"JSON 包含非有限常量：{value}")

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        raise _incompatible(
            "模型包 JSON 文件无法解析", {"file": path.name}
        ) from error
    if not isinstance(payload, dict):
        raise _incompatible(
            "模型包 JSON 顶层必须是对象", {"file": path.name}
        )
    return payload


def _parse_labels(payload: Mapping[Any, Any]) -> dict[int, str]:
    if not isinstance(payload, Mapping):
        raise _incompatible("模型类别映射必须是对象")
    try:
        labels = {
            int(index): label
            for index, label in payload.items()
            if (
                isinstance(index, str)
                and re.fullmatch(r"(?:0|[1-9]\d*)", index)
                and isinstance(label, str)
                and label
            )
        }
    except (TypeError, ValueError) as error:
        raise _incompatible("模型类别映射非法") from error
    if len(labels) != len(payload):
        raise _incompatible("模型类别索引或名称格式非法")
    if sorted(labels) != list(range(len(labels))):
        raise _incompatible("模型类别索引必须从 0 连续递增")
    return labels


def _verify_preprocessing(
    manifest: ModelManifest,
    payload: Mapping[str, Any],
) -> None:
    expected = {
        "plugin_id": manifest.preprocessor.plugin_id,
        "plugin_version": manifest.preprocessor.plugin_version,
        "config_hash": manifest.preprocessor.config_sha256,
    }
    if dict(payload) != expected:
        raise _incompatible("preprocessing.json 与模型清单不一致")


def _verify_approval(
    manifest: ModelManifest,
    package_sha256: str,
    signer_key_id: str,
    approved: ApprovedArtifact,
) -> None:
    if approved.approval_state not in {"APPROVED", "DEPLOYABLE"}:
        raise _incompatible("模型包未获部署批准")
    if _SHA256.fullmatch(approved.package_sha256) is None:
        raise _incompatible("批准记录的模型包哈希格式非法")
    expected = (
        approved.model_name,
        approved.model_version,
        approved.package_sha256,
        approved.signer_key_id,
    )
    actual = (
        manifest.model_name,
        manifest.model_version,
        package_sha256,
        signer_key_id,
    )
    if expected != actual:
        raise _incompatible(
            "模型包与批准记录不一致",
            {"expected": list(expected), "actual": list(actual)},
        )


def _incompatible(
    message: str,
    details: Mapping[str, Any] | None = None,
) -> PluginError:
    return PluginError.create(
        PluginErrorCode.MODEL_INCOMPATIBLE,
        "artifact_verification",
        message,
        details,
    )
