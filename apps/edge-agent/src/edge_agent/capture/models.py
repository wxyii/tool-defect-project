"""采集进程内对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Tuple


@dataclass(frozen=True)
class CapturedFrame:
    image_role: str
    content: bytes
    media_type: str = "image/png"
    extension: str = "png"
    width: Optional[int] = None
    height: Optional[int] = None
    bit_depth: Optional[int] = None
    channels: Optional[int] = None
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FrameQuality:
    status: str
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PersistedImage:
    image_role: str
    relative_path: Path
    sha256: str
    size_bytes: int
    media_type: str
    width: int
    height: int


@dataclass(frozen=True)
class PersistedCapture:
    capture_id: str
    directory: Path
    manifest_path: Path
    images: Tuple[PersistedImage, ...]
    quality: FrameQuality
