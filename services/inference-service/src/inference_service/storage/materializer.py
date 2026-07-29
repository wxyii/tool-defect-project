"""对象下载、大小和哈希校验。"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping, Protocol

from tool_defect.plugin_api import PluginError, PluginErrorCode


_SHA256 = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{0,127}$")
_OBJECT_KEY = re.compile(
    r"^(?!/)(?![A-Za-z]:)(?!https?://)[A-Za-z0-9][A-Za-z0-9._/-]*$"
)
_IMAGE_KINDS = {
    "RAW",
    "THUMBNAIL",
    "DEFECT_MASK",
    "HEATMAP",
    "OVERLAY",
    "POLAR",
    "REVIEW_MASK",
}


@dataclass(frozen=True)
class ObjectReference:
    image_id: str
    object_key: str
    sha256: str
    media_type: str
    size_bytes: int
    bucket: str = "td-original"
    object_version: str | None = None
    kind: str = "RAW"
    width: int | None = None
    height: int | None = None
    image_role: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.image_id, str)
            or not self.image_id
            or not isinstance(self.object_key, str)
            or not self.object_key
        ):
            raise ValueError("对象引用标识和对象键不能为空")
        if (
            not isinstance(self.bucket, str)
            or _BUCKET.fullmatch(self.bucket) is None
            or _OBJECT_KEY.fullmatch(self.object_key) is None
            or ".." in self.object_key.split("/")
        ):
            raise ValueError("对象引用桶或对象键格式非法")
        if _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("对象引用 SHA-256 格式非法")
        if (
            not isinstance(self.media_type, str)
            or self.media_type not in {"image/png", "image/jpeg"}
        ):
            raise ValueError("对象引用媒体类型不在冻结图片契约中")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes <= 0
        ):
            raise ValueError("对象引用大小必须是正整数")
        if self.object_version is not None and (
            not isinstance(self.object_version, str)
            or len(self.object_version) > 256
        ):
            raise ValueError("对象版本格式非法")
        if self.kind not in _IMAGE_KINDS:
            raise ValueError("图片类型不在冻结枚举中")
        if (self.width is None) != (self.height is None):
            raise ValueError("图片宽高必须同时提供或同时省略")
        if self.width is not None and any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            or value > 32768
            for value in (self.width, self.height)
        ):
            raise ValueError("图片宽高超出冻结契约范围")
        if self.image_role is not None and (
            not isinstance(self.image_role, str)
            or not self.image_role
            or len(self.image_role) > 64
        ):
            raise ValueError("图片角色格式非法")

    @classmethod
    def from_contract(cls, payload: Mapping[str, Any]) -> "ObjectReference":
        if not isinstance(payload, Mapping):
            raise TypeError("图片引用必须是对象")
        allowed = {
            "image_id",
            "kind",
            "object",
            "width",
            "height",
            "image_role",
        }
        required = allowed.difference({"image_role"})
        if set(payload).difference(allowed) or not required.issubset(payload):
            raise ValueError("图片引用字段与冻结契约不一致")
        object_payload = payload["object"]
        if not isinstance(object_payload, Mapping):
            raise TypeError("对象引用必须是对象")
        object_allowed = {
            "bucket",
            "object_key",
            "object_version",
            "sha256",
            "size_bytes",
            "media_type",
        }
        object_required = object_allowed.difference({"object_version"})
        if set(object_payload).difference(
            object_allowed
        ) or not object_required.issubset(object_payload):
            raise ValueError("对象存储引用字段与冻结契约不一致")
        return cls(
            image_id=payload["image_id"],
            object_key=object_payload["object_key"],
            sha256=object_payload["sha256"],
            media_type=object_payload["media_type"],
            size_bytes=object_payload["size_bytes"],
            bucket=object_payload["bucket"],
            object_version=object_payload.get("object_version"),
            kind=payload["kind"],
            width=payload["width"],
            height=payload["height"],
            image_role=payload.get("image_role"),
        )


@dataclass(frozen=True)
class MaterializedObject:
    reference: ObjectReference
    path: Path
    sha256: str
    size_bytes: int


class ObjectReader(Protocol):
    async def download(
        self,
        reference: ObjectReference,
        destination: Path,
    ) -> None:
        ...


class ObjectMaterializer:
    def __init__(
        self,
        reader: ObjectReader,
        *,
        maximum_bytes: int = 64 * 1024 * 1024,
    ):
        self._reader = reader
        self._maximum_bytes = int(maximum_bytes)
        if self._maximum_bytes <= 0:
            raise ValueError("对象物化大小限制必须为正数")

    async def materialize(
        self,
        reference: ObjectReference,
        temp_dir: Path,
    ) -> MaterializedObject:
        match = _SHA256.fullmatch(reference.sha256)
        if (
            match is None
            or not reference.image_id
            or reference.size_bytes <= 0
            or reference.size_bytes > self._maximum_bytes
        ):
            raise PluginError.create(
                PluginErrorCode.INPUT_INVALID,
                "download",
                "对象引用的哈希或大小非法",
            )
        temp_dir.mkdir(parents=True, exist_ok=True)
        local_name = hashlib.sha256(
            reference.image_id.encode("utf-8")
        ).hexdigest()
        destination = temp_dir / f"{local_name}.object"
        await self._reader.download(reference, destination)
        if destination.is_symlink() or not destination.is_file():
            raise PluginError.create(
                PluginErrorCode.INPUT_INVALID,
                "download",
                "对象下载结果不是普通文件",
            )
        size = destination.stat().st_size
        if size != reference.size_bytes or size > self._maximum_bytes:
            raise PluginError.create(
                PluginErrorCode.INPUT_INVALID,
                "download",
                "对象下载大小与引用不一致",
                {"expected": reference.size_bytes, "actual": size},
            )
        digest = _file_sha256(destination)
        if digest != match.group(1):
            raise PluginError.create(
                PluginErrorCode.INPUT_INVALID,
                "download",
                "对象下载 SHA-256 与引用不一致",
                {"expected": match.group(1), "actual": digest},
            )
        return MaterializedObject(
            reference=reference,
            path=destination,
            sha256=digest,
            size_bytes=size,
        )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
