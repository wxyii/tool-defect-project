"""R8 模型压缩包的隔离检查与安全解包。

该模块只处理模型包的容器边界，不加载模型、不执行包内代码，也不访问业务数据库。
验证通过后返回不可变的文件哈希证据；解包过程仍会重新确认外层包摘要，避免验证与落盘之间
发生替换。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
from typing import Any, Mapping, NoReturn
import zipfile


SHA256 = re.compile(r"^[0-9a-f]{64}$")
DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")

DEFAULT_REQUIRED_FILES = frozenset(
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
        "sbom.json",
    }
)
DEFAULT_OPTIONAL_FILES = frozenset({"warmup-input.npy", "warmup-expected.json"})
DEFAULT_ALLOWED_FILES = DEFAULT_REQUIRED_FILES | DEFAULT_OPTIONAL_FILES
DEFAULT_FORBIDDEN_SUFFIXES = frozenset(
    {".py", ".pyc", ".pyd", ".so", ".dll", ".dylib", ".sh", ".bat", ".ps1"}
)


@dataclass(frozen=True)
class ArchiveLimits:
    """模型包容器限制；调用方应按批准的隔离资源预算显式覆盖。"""

    maximum_archive_bytes: int = 8 * 1024 * 1024 * 1024
    maximum_member_bytes: int = 8 * 1024 * 1024 * 1024
    maximum_total_uncompressed_bytes: int = 8 * 1024 * 1024 * 1024
    maximum_entries: int = 128
    maximum_compression_ratio: int = 1000

    def __post_init__(self) -> None:
        values = (
            self.maximum_archive_bytes,
            self.maximum_member_bytes,
            self.maximum_total_uncompressed_bytes,
            self.maximum_entries,
            self.maximum_compression_ratio,
        )
        if any(not isinstance(value, int) or value <= 0 for value in values):
            raise ValueError("模型包限制必须全部为正整数")


class ModelArchiveViolation(ValueError):
    """可安全展示的模型包失败；不携带路径、密钥或堆栈等敏感细节。"""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details)


@dataclass(frozen=True)
class ModelArchiveEvidence:
    archive_sha256: str
    archive_size_bytes: int
    member_sha256: Mapping[str, str]
    member_size_bytes: Mapping[str, int]
    signer_key_id: str
    manifest: Mapping[str, Any]


def verify_model_archive(
    archive_path: Path,
    *,
    declared_size_bytes: int,
    declared_sha256: str,
    trusted_public_keys: Mapping[str, bytes],
    limits: ArchiveLimits = ArchiveLimits(),
    required_files: frozenset[str] = DEFAULT_REQUIRED_FILES,
    optional_files: frozenset[str] = DEFAULT_OPTIONAL_FILES,
    forbidden_suffixes: frozenset[str] = DEFAULT_FORBIDDEN_SUFFIXES,
) -> ModelArchiveEvidence:
    """在不执行包内内容的前提下验证外层压缩包、清单、哈希和签名。"""

    path = Path(archive_path)
    if path.is_symlink() or not path.is_file():
        _fail("ARCHIVE_NOT_REGULAR_FILE", "模型包不是普通文件")
    if not isinstance(declared_size_bytes, int) or declared_size_bytes <= 0:
        _fail("DECLARED_SIZE_INVALID", "声明的模型包大小无效")
    if not isinstance(declared_sha256, str) or SHA256.fullmatch(declared_sha256) is None:
        _fail("DECLARED_SHA256_INVALID", "声明的模型包哈希无效")
    if not trusted_public_keys:
        _fail("TRUST_ROOT_MISSING", "模型签名信任根缺失")

    try:
        archive_size = path.stat().st_size
    except OSError as error:
        _fail("ARCHIVE_STAT_FAILED", "无法读取模型包大小", exception_type=type(error).__name__)
    if archive_size != declared_size_bytes:
        _fail(
            "ARCHIVE_SIZE_MISMATCH",
            "模型包实际大小与声明不一致",
            declared=declared_size_bytes,
            actual=archive_size,
        )
    if archive_size > limits.maximum_archive_bytes:
        _fail("ARCHIVE_SIZE_LIMIT", "模型包超过隔离大小上限")
    archive_sha256 = _sha256_file(path)
    if archive_sha256 != declared_sha256:
        _fail("ARCHIVE_SHA256_MISMATCH", "模型包实际哈希与声明不一致")

    try:
        with zipfile.ZipFile(path, "r") as archive:
            entries = _validate_entries(
                archive,
                limits=limits,
                required_files=required_files,
                optional_files=optional_files,
                forbidden_suffixes=forbidden_suffixes,
            )
            member_sha256, member_sizes = _hash_entries(archive, entries, limits)
            manifest = _load_manifest(archive, entries)
            _validate_checksums(
                archive,
                entries,
                member_sha256,
                required_files,
                optional_files,
                limits,
            )
            signer_key_id = _validate_signature(
                archive,
                entries,
                trusted_public_keys,
                limits,
            )
    except ModelArchiveViolation:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as error:
        _fail("ARCHIVE_INVALID", "模型包不是可验证的 ZIP 文件", exception_type=type(error).__name__)

    return ModelArchiveEvidence(
        archive_sha256=archive_sha256,
        archive_size_bytes=archive_size,
        member_sha256=dict(member_sha256),
        member_size_bytes=dict(member_sizes),
        signer_key_id=signer_key_id,
        manifest=dict(manifest),
    )


def extract_verified_model_archive(
    archive_path: Path,
    destination: Path,
    evidence: ModelArchiveEvidence,
    *,
    limits: ArchiveLimits = ArchiveLimits(),
) -> Path:
    """把已验证包解到新目录；再次确认外层摘要并拒绝任何替换或特殊文件。"""

    archive = Path(archive_path)
    target = Path(destination)
    if archive.is_symlink() or not archive.is_file():
        _fail("ARCHIVE_NOT_REGULAR_FILE", "模型包不是普通文件")
    if _sha256_file(archive) != evidence.archive_sha256:
        _fail("ARCHIVE_CHANGED_AFTER_VERIFY", "模型包在验证后发生变化")
    if archive.stat().st_size != evidence.archive_size_bytes:
        _fail("ARCHIVE_CHANGED_AFTER_VERIFY", "模型包在验证后发生变化")
    if target.exists() and target.is_symlink():
        _fail("EXTRACTION_TARGET_SYMLINK", "解包目录不能是符号链接")
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve(strict=True)
    if not root.is_dir():
        _fail("EXTRACTION_TARGET_INVALID", "解包目标不是目录")
    try:
        if any(root.iterdir()):
            _fail("EXTRACTION_TARGET_NOT_EMPTY", "解包目标必须为空目录")
    except OSError as error:
        _fail("EXTRACTION_TARGET_INVALID", "无法读取解包目标", exception_type=type(error).__name__)

    try:
        with zipfile.ZipFile(archive, "r") as source:
            entries = _validate_entries(
                source,
                limits=limits,
                required_files=frozenset(evidence.member_sha256),
                optional_files=frozenset(),
                forbidden_suffixes=DEFAULT_FORBIDDEN_SUFFIXES,
            )
            for info in entries:
                name = _safe_member_name(info.filename)
                output = (root / Path(*PurePosixPath(name).parts)).resolve()
                if output.parent != root:
                    _fail("EXTRACTION_PATH_ESCAPE", "模型包文件越过解包目录")
                if output.exists() or output.is_symlink():
                    _fail("EXTRACTION_TARGET_NOT_EMPTY", "解包目标不是空目录")
                with source.open(info, "r") as input_stream, output.open("xb") as file:
                    digest = hashlib.sha256()
                    actual_size = 0
                    while chunk := input_stream.read(1024 * 1024):
                        actual_size += len(chunk)
                        if actual_size > limits.maximum_member_bytes:
                            _fail("MEMBER_SIZE_LIMIT", "模型包成员超过大小上限")
                        digest.update(chunk)
                        file.write(chunk)
                    if actual_size != info.file_size:
                        _fail("MEMBER_SIZE_MISMATCH", "模型包成员解压大小不一致")
                    if evidence.member_sha256.get(name) != digest.hexdigest():
                        _fail("MEMBER_SHA256_MISMATCH", "模型包成员哈希发生变化")
                    if evidence.member_size_bytes.get(name) != actual_size:
                        _fail("MEMBER_SIZE_MISMATCH", "模型包成员大小发生变化")
                output.chmod(0o600)
    except ModelArchiveViolation:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as error:
        _fail("EXTRACTION_FAILED", "模型包安全解包失败", exception_type=type(error).__name__)
    return root


def _validate_entries(
    archive: zipfile.ZipFile,
    *,
    limits: ArchiveLimits,
    required_files: frozenset[str],
    optional_files: frozenset[str],
    forbidden_suffixes: frozenset[str],
) -> tuple[zipfile.ZipInfo, ...]:
    infos = archive.infolist()
    if not infos:
        _fail("ARCHIVE_EMPTY", "模型包为空")
    if len(infos) > limits.maximum_entries:
        _fail("ENTRY_COUNT_LIMIT", "模型包文件数量超过限制")
    allowed_files = required_files | optional_files
    seen: set[str] = set()
    total_uncompressed = 0
    valid: list[zipfile.ZipInfo] = []
    for info in infos:
        name = _safe_member_name(info.filename)
        if name in seen:
            _fail("DUPLICATE_MEMBER", "模型包包含重复文件名")
        seen.add(name)
        if info.is_dir():
            _fail("DIRECTORY_MEMBER", "模型包不允许目录条目")
        if info.flag_bits & 0x1:
            _fail("ENCRYPTED_MEMBER", "模型包不允许加密条目")
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            _fail("COMPRESSION_NOT_ALLOWED", "模型包压缩算法不在白名单")
        _reject_special_file(info)
        if any(name.lower().endswith(suffix) for suffix in forbidden_suffixes):
            _fail("FORBIDDEN_FILE_TYPE", "模型包包含禁止的可执行文件类型")
        if name not in allowed_files:
            _fail("UNDECLARED_MEMBER", "模型包包含未声明文件")
        if info.file_size < 0 or info.file_size > limits.maximum_member_bytes:
            _fail("MEMBER_SIZE_LIMIT", "模型包成员超过大小上限")
        if info.compress_size < 0:
            _fail("MEMBER_COMPRESSED_SIZE_INVALID", "模型包成员压缩大小无效")
        if info.file_size and info.compress_size == 0:
            _fail("COMPRESSION_BOMB", "模型包成员压缩比例异常")
        if info.file_size and info.file_size > max(1, info.compress_size) * limits.maximum_compression_ratio:
            _fail("COMPRESSION_BOMB", "模型包成员压缩比例超过限制")
        total_uncompressed += info.file_size
        if total_uncompressed > limits.maximum_total_uncompressed_bytes:
            _fail("TOTAL_UNCOMPRESSED_LIMIT", "模型包解压总大小超过限制")
        valid.append(info)

    missing = required_files - seen
    if missing:
        _fail("REQUIRED_MEMBER_MISSING", "模型包缺少必需文件", missing=sorted(missing))
    warmup = optional_files & seen
    if warmup and warmup != optional_files:
        _fail("WARMUP_PAIR_INCOMPLETE", "固定预热输入和期望结果必须成对提供")
    return tuple(valid)


def _hash_entries(
    archive: zipfile.ZipFile,
    entries: tuple[zipfile.ZipInfo, ...],
    limits: ArchiveLimits,
) -> tuple[dict[str, str], dict[str, int]]:
    hashes: dict[str, str] = {}
    sizes: dict[str, int] = {}
    for info in entries:
        digest = hashlib.sha256()
        actual_size = 0
        try:
            with archive.open(info, "r") as stream:
                while chunk := stream.read(1024 * 1024):
                    actual_size += len(chunk)
                    if actual_size > limits.maximum_member_bytes:
                        _fail("MEMBER_SIZE_LIMIT", "模型包成员超过大小上限")
                    digest.update(chunk)
        except ModelArchiveViolation:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile) as error:
            _fail("MEMBER_READ_FAILED", "模型包成员读取失败", exception_type=type(error).__name__)
        if actual_size != info.file_size:
            _fail("MEMBER_SIZE_MISMATCH", "模型包成员解压大小不一致")
        hashes[info.filename] = digest.hexdigest()
        sizes[info.filename] = actual_size
    return hashes, sizes


def _load_manifest(
    archive: zipfile.ZipFile,
    entries: tuple[zipfile.ZipInfo, ...],
) -> Mapping[str, Any]:
    names = {entry.filename for entry in entries}
    if "manifest.json" not in names:
        _fail("MANIFEST_MISSING", "模型包清单缺失")
    payload = _read_entry(archive, "manifest.json", 2 * 1024 * 1024)
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"非有限 JSON 常量: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        _fail("MANIFEST_INVALID", "模型包清单不是有效 JSON", exception_type=type(error).__name__)
    if not isinstance(value, dict):
        _fail("MANIFEST_INVALID", "模型包清单根节点必须是对象")
    for field in ("model_name", "model_version", "framework"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            _fail("MANIFEST_FIELD_MISSING", "模型包清单缺少必要字段", field=field)
    declared_files = value.get("files")
    if not isinstance(declared_files, list) or any(
        not isinstance(item, str) or not item.strip() for item in declared_files
    ):
        _fail("MANIFEST_FILES_MISSING", "模型包清单必须声明文件列表")
    if len(set(declared_files)) != len(declared_files) or any(
        _safe_member_name(item) != item for item in declared_files
    ):
        _fail("MANIFEST_FILES_INVALID", "模型包清单文件列表包含重复或危险路径")
    if set(declared_files) != names - {"manifest.json"}:
        _fail("MANIFEST_FILES_MISMATCH", "模型包清单文件列表与压缩包不一致")
    return value


def _validate_checksums(
    archive: zipfile.ZipFile,
    entries: tuple[zipfile.ZipInfo, ...],
    member_sha256: Mapping[str, str],
    required_files: frozenset[str],
    optional_files: frozenset[str],
    limits: ArchiveLimits,
) -> None:
    expected = (required_files | (optional_files & set(member_sha256))) - {
        "checksums.sha256",
        "signature.sig",
    }
    payload = _read_entry(archive, "checksums.sha256", limits.maximum_member_bytes)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail("CHECKSUM_MANIFEST_INVALID", "模型包哈希清单不是 UTF-8", exception_type=type(error).__name__)
    actual: dict[str, str] = {}
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", raw_line)
        if match is None:
            _fail("CHECKSUM_MANIFEST_INVALID", "模型包哈希清单格式无效")
        digest, name = match.groups()
        _safe_member_name(name)
        if name in actual:
            _fail("CHECKSUM_MANIFEST_INVALID", "模型包哈希清单包含重复文件")
        actual[name] = digest
    if set(actual) != expected:
        _fail("CHECKSUM_SET_MISMATCH", "模型包哈希清单文件集合不一致")
    for name, expected_hash in actual.items():
        if member_sha256.get(name) != expected_hash:
            _fail("MEMBER_SHA256_MISMATCH", "模型包文件哈希与清单不一致")


def _validate_signature(
    archive: zipfile.ZipFile,
    entries: tuple[zipfile.ZipInfo, ...],
    trusted_public_keys: Mapping[str, bytes],
    limits: ArchiveLimits,
) -> str:
    names = {entry.filename for entry in entries}
    if "signature.sig" not in names:
        _fail("SIGNATURE_MISSING", "模型包签名缺失")
    payload = _read_entry(archive, "signature.sig", limits.maximum_member_bytes)
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        _fail("SIGNATURE_INVALID", "模型包签名文件无效", exception_type=type(error).__name__)
    if not isinstance(value, dict) or set(value) != {"algorithm", "key_id", "signature_base64"}:
        _fail("SIGNATURE_INVALID", "模型包签名字段不完整")
    if value["algorithm"] != "ed25519" or not all(
        isinstance(value[field], str) and value[field].strip()
        for field in ("key_id", "signature_base64")
    ):
        _fail("SIGNATURE_INVALID", "模型包签名算法或字段无效")
    key_id = value["key_id"]
    if key_id not in trusted_public_keys:
        _fail("SIGNER_NOT_TRUSTED", "模型包签名密钥不在信任根中")
    try:
        signature = base64.b64decode(value["signature_base64"], validate=True)
        key_bytes = trusted_public_keys[key_id]
        if not isinstance(key_bytes, bytes) or len(key_bytes) != 32:
            _fail("TRUST_ROOT_INVALID", "模型签名信任根无效")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        checksums = _read_entry(archive, "checksums.sha256", limits.maximum_member_bytes)
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(signature, checksums)
    except ModelArchiveViolation:
        raise
    except Exception as error:
        _fail("SIGNATURE_INVALID", "模型包数字签名验证失败", exception_type=type(error).__name__)
    return key_id


def _read_entry(archive: zipfile.ZipFile, name: str, maximum_bytes: int) -> bytes:
    try:
        info = archive.getinfo(name)
        with archive.open(info, "r") as stream:
            chunks: list[bytes] = []
            total = 0
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > maximum_bytes:
                    _fail("MEMBER_SIZE_LIMIT", "模型包成员超过大小上限")
                chunks.append(chunk)
            return b"".join(chunks)
    except KeyError:
        _fail("REQUIRED_MEMBER_MISSING", "模型包缺少必要文件")
    except ModelArchiveViolation:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        _fail("MEMBER_READ_FAILED", "模型包成员读取失败", exception_type=type(error).__name__)


def _safe_member_name(name: str) -> str:
    if not isinstance(name, str) or not name or "\x00" in name:
        _fail("UNSAFE_MEMBER_NAME", "模型包文件名无效")
    if "\\" in name or name.startswith("/") or DRIVE_PREFIX.match(name):
        _fail("PATH_TRAVERSAL", "模型包文件名不是安全相对路径")
    normalized = posixpath.normpath(name)
    if normalized != name or normalized in {"", ".", ".."}:
        _fail("PATH_TRAVERSAL", "模型包文件名包含路径穿越")
    parts = PurePosixPath(name).parts
    if any(part in {"", ".", ".."} for part in parts) or PurePosixPath(name).is_absolute():
        _fail("PATH_TRAVERSAL", "模型包文件名包含路径穿越")
    return name


def _reject_special_file(info: zipfile.ZipInfo) -> None:
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if file_type in {stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK}:
        _fail("SPECIAL_FILE_MEMBER", "模型包不允许链接、设备或特殊文件")
    if file_type not in {0, stat.S_IFREG}:
        _fail("SPECIAL_FILE_MEMBER", "模型包包含不支持的文件类型")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        _fail("ARCHIVE_READ_FAILED", "无法读取模型包", exception_type=type(error).__name__)
    return digest.hexdigest()


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("重复 JSON 字段")
        result[key] = value
    return result


def _fail(code: str, message: str, **details: object) -> NoReturn:
    raise ModelArchiveViolation(code, message, **details)
