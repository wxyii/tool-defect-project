"""可恢复的原子目录落盘。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Optional
import warnings

from PIL import Image, UnidentifiedImageError

from .models import (
    CapturedFrame,
    FrameQuality,
    PersistedCapture,
    PersistedImage,
)
from ..local_queue.database import EdgeQueue, QueueIntegrityError
from ..local_queue.models import LocalCaptureState, LocalImageRecord


class CaptureStorageError(RuntimeError):
    """原子落盘或恢复失败。"""


class InjectedCrash(RuntimeError):
    """测试用受控崩溃点。"""


def _default_decoder_probe(frame: CapturedFrame) -> tuple[bool, tuple[str, ...]]:
    if not frame.content:
        return False, ("EMPTY_FILE",)
    quality_warnings: list[str] = []
    if frame.metadata.get("all_black") is True:
        quality_warnings.append("ALL_BLACK")
    if frame.metadata.get("all_white") is True:
        quality_warnings.append("ALL_WHITE")
    expected_format = {
        "image/png": "PNG",
        "image/jpeg": "JPEG",
    }.get(frame.media_type)
    try:
        if expected_format is None:
            raise UnidentifiedImageError("不支持的媒体类型")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(frame.content)) as image:
                if image.format != expected_format:
                    raise UnidentifiedImageError("文件格式与 media_type 不一致")
                dimensions = image.size
                image.verify()
            # verify() 会使解析器失效，重新打开并 load() 才能验证完整像素流。
            with Image.open(BytesIO(frame.content)) as decoded:
                decoded.load()
                extrema = decoded.convert("L").getextrema()
                if extrema == (0, 0):
                    quality_warnings.append("ALL_BLACK")
                elif extrema == (255, 255):
                    quality_warnings.append("ALL_WHITE")
        if (
            (frame.width is not None and frame.width != dimensions[0])
            or (frame.height is not None and frame.height != dimensions[1])
        ):
            quality_warnings.append("DIMENSION_MISMATCH")
            raise OSError("声明尺寸与解码尺寸不一致")
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ):
        quality_warnings.append("IMAGE_DECODE_FAILED")
        return False, tuple(sorted(set(quality_warnings)))
    return True, tuple(sorted(set(quality_warnings)))


def _image_dimensions(frame: CapturedFrame) -> tuple[int, int]:
    if (
        frame.width is not None
        and frame.height is not None
        and frame.width > 0
        and frame.height > 0
    ):
        return frame.width, frame.height
    content = frame.content
    if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
        width = int.from_bytes(content[16:20], "big")
        height = int.from_bytes(content[20:24], "big")
        if width > 0 and height > 0:
            return width, height
    if content.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 < len(content):
            if content[offset] != 0xFF:
                offset += 1
                continue
            marker = content[offset + 1]
            if marker in {0xD8, 0xD9}:
                offset += 2
                continue
            if offset + 4 > len(content):
                break
            segment_length = int.from_bytes(content[offset + 2 : offset + 4], "big")
            if segment_length < 2 or offset + 2 + segment_length > len(content):
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                height = int.from_bytes(content[offset + 5 : offset + 7], "big")
                width = int.from_bytes(content[offset + 7 : offset + 9], "big")
                if width > 0 and height > 0:
                    return width, height
            offset += 2 + segment_length
    raise CaptureStorageError("图片尺寸缺失且无法从文件头解析")


class AtomicCaptureStore:
    """维护 `staging/pending/confirmed/quarantine` 目录。

    目录改名先于 SQLite 事务；若数据库写入失败，启动扫描依据
    `manifest.json` 重建同步投影。
    """

    def __init__(
        self,
        root: Path | str,
        queue: EdgeQueue,
        *,
        decoder_probe: Callable[[CapturedFrame], tuple[bool, tuple[str, ...]]] = (
            _default_decoder_probe
        ),
        crash_hook: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.root = Path(root)
        self.queue = queue
        self.decoder_probe = decoder_probe
        self.crash_hook = crash_hook
        self.staging = self.root / "staging"
        self.pending = self.root / "pending"
        self.confirmed = self.root / "confirmed"
        self.quarantine = self.root / "quarantine"
        for directory in (
            self.staging,
            self.pending,
            self.confirmed,
            self.quarantine,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def persist(
        self,
        *,
        capture_id: str,
        station_id: str,
        recipe_id: str,
        client_sequence: int,
        occurred_at: str,
        frames: Iterable[CapturedFrame],
        trigger_id: str,
        trigger_source: str,
        quality_warnings: Iterable[str] = (),
    ) -> PersistedCapture:
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", capture_id)
            is None
            or capture_id in {".", ".."}
        ):
            raise CaptureStorageError("capture_id 不能用于目录穿越")
        frame_list = list(frames)
        if not frame_list:
            raise CaptureStorageError("相机没有产生任何文件")
        if len(frame_list) > 16:
            raise CaptureStorageError("单次采集图片数量超过冻结契约上限 16")
        roles = [frame.image_role for frame in frame_list]
        normalized_roles = [role.casefold() for role in roles]
        if len(normalized_roles) != len(set(normalized_roles)):
            raise CaptureStorageError("多帧 image_role 必须唯一")
        if any(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", role) is None
            for role in roles
        ):
            raise CaptureStorageError(
                "image_role 必须是 1 至 64 位安全路径片段"
            )
        if not station_id or not recipe_id:
            raise CaptureStorageError("station_id 和 recipe_id 不能为空")
        if trigger_source not in {"PLC", "SENSOR", "MANUAL", "HISTORICAL_IMPORT"}:
            raise CaptureStorageError("触发来源不属于冻结契约")

        stage_directory = self.staging / f"{capture_id}.tmp"
        target_directory = self.pending / capture_id
        if target_directory.exists():
            persisted = self._read_persisted(target_directory)
            if self.queue.get_capture(capture_id) is None:
                manifest = self._read_manifest(target_directory)
                self._create_queue_record(
                    manifest=manifest,
                    manifest_path=persisted.manifest_path,
                    images=list(persisted.images),
                )
            return persisted
        if stage_directory.exists():
            self._quarantine_path(stage_directory, "stale-staging")
        stage_directory.mkdir(mode=0o700)

        persisted_images: list[PersistedImage] = []
        warnings = list(quality_warnings)
        rejected = False
        try:
            for frame in frame_list:
                extension = frame.extension.lower().lstrip(".")
                if not extension.isalnum():
                    raise CaptureStorageError("图片扩展名不合法")
                file_name = f"{frame.image_role.lower()}.{extension}"
                destination = stage_directory / file_name
                digest = hashlib.sha256()
                with destination.open("xb") as handle:
                    handle.write(frame.content)
                    digest.update(frame.content)
                    handle.flush()
                    os.fsync(handle.fileno())
                if not frame.content:
                    raise CaptureStorageError(f"{frame.image_role} 没有产生文件内容")
                width, height = _image_dimensions(frame)
                accepted, frame_warnings = self.decoder_probe(frame)
                warnings.extend(frame_warnings)
                rejected = rejected or not accepted
                persisted_images.append(
                    PersistedImage(
                        image_role=frame.image_role,
                        relative_path=Path("pending") / capture_id / file_name,
                        sha256=digest.hexdigest(),
                        size_bytes=len(frame.content),
                        media_type=frame.media_type,
                        width=width,
                        height=height,
                    )
                )
            quality = FrameQuality(
                status=(
                    "REJECTED"
                    if rejected
                    else ("WARNING" if warnings else "OK")
                ),
                warnings=tuple(sorted(set(warnings))),
            )
            manifest = {
                "schema_version": 1,
                "capture_id": capture_id,
                "station_id": station_id,
                "recipe_id": recipe_id,
                "trigger": {
                    "trigger_id": trigger_id,
                    "client_sequence": client_sequence,
                    "occurred_at": occurred_at,
                    "source": trigger_source,
                },
                "quality": {
                    "status": quality.status,
                    "warnings": list(quality.warnings),
                },
                "images": [
                    {
                        "client_image_id": image.image_role.lower(),
                        "image_role": image.image_role,
                        "file_name": image.relative_path.name,
                        "relative_path": image.relative_path.as_posix(),
                        "sha256": image.sha256,
                        "size_bytes": image.size_bytes,
                        "media_type": image.media_type,
                        "width": image.width,
                        "height": image.height,
                    }
                    for image in persisted_images
                ],
            }
            manifest_path = stage_directory / "manifest.json"
            encoded = (
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            with manifest_path.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            self._sync_directory(stage_directory)
            self._crash("after_file_sync")
            os.replace(stage_directory, target_directory)
            self._sync_directory(self.pending)
            self._crash("after_directory_rename")

            relative_manifest = (
                Path("pending") / capture_id / "manifest.json"
            )
            self._create_queue_record(
                manifest=manifest,
                manifest_path=relative_manifest,
                images=persisted_images,
            )
            self._crash("after_sqlite_commit")
            return PersistedCapture(
                capture_id=capture_id,
                directory=target_directory,
                manifest_path=relative_manifest,
                images=tuple(persisted_images),
                quality=quality,
            )
        except InjectedCrash:
            raise
        except BaseException:
            if stage_directory.exists():
                self._quarantine_path(stage_directory, "write-failed")
            raise

    def recover(self) -> dict[str, list[str]]:
        """扫描崩溃窗口并恢复缺失队列项。

        完整临时目录继续完成原子改名；不完整目录进入隔离。已改名且
        清单完整的目录重建 SQLite。
        """

        recovered: list[str] = []
        quarantined: list[str] = []
        for stage_path in sorted(self.staging.glob("*.tmp")):
            try:
                persisted = self._read_persisted(stage_path)
                capture_id = persisted.capture_id
                target = self.pending / capture_id
                if target.exists():
                    raise CaptureStorageError("暂存恢复目标已经存在")
                os.replace(stage_path, target)
                self._sync_directory(self.pending)
                persisted = self._read_persisted(target)
                manifest = self._read_manifest(target)
                self._create_queue_record(
                    manifest=manifest,
                    manifest_path=persisted.manifest_path,
                    images=list(persisted.images),
                )
                recovered.append(capture_id)
            except BaseException:
                if stage_path.exists():
                    quarantined.append(stage_path.name)
                    self._quarantine_path(stage_path, "startup-incomplete")

        # 数据库重建后，已确认目录也失去可证明的中心投影。保守地放回
        # pending，再由批量对账恢复，而不是继续允许清理。
        for confirmed_directory in sorted(self.confirmed.iterdir()):
            if not confirmed_directory.is_dir():
                continue
            capture_id = confirmed_directory.name
            existing = self.queue.get_capture(capture_id)
            try:
                persisted = self._read_persisted(confirmed_directory)
                manifest = self._read_manifest(confirmed_directory)
                if existing is not None:
                    self._create_queue_record(
                        manifest=manifest,
                        manifest_path=persisted.manifest_path,
                        images=list(persisted.images),
                    )
            except BaseException:
                quarantined.append(capture_id)
                self._quarantine_path(
                    confirmed_directory,
                    "integrity-invalid",
                )
                self._record_integrity_failure(capture_id)
                continue
            if existing is not None:
                continue
            target = self.pending / capture_id
            if target.exists():
                quarantined.append(capture_id)
                self._quarantine_path(
                    confirmed_directory,
                    "confirmed-recovery-conflict",
                )
                continue
            os.replace(confirmed_directory, target)
            self._sync_directory(self.confirmed)
            self._sync_directory(self.pending)

        for capture_directory in sorted(self.pending.iterdir()):
            if not capture_directory.is_dir():
                continue
            capture_id = capture_directory.name
            existing = self.queue.get_capture(capture_id)
            try:
                persisted = self._read_persisted(capture_directory)
                manifest = self._read_manifest(capture_directory)
                self._create_queue_record(
                    manifest=manifest,
                    manifest_path=persisted.manifest_path,
                    images=list(persisted.images),
                )
                if existing is None:
                    recovered.append(capture_id)
            except BaseException:
                quarantined.append(capture_id)
                self._quarantine_path(capture_directory, "manifest-invalid")
                self._record_integrity_failure(capture_id)
        return {"recovered": recovered, "quarantined": quarantined}

    def mark_confirmed(self, capture_id: str) -> Path:
        record = self.queue.get_capture(capture_id)
        if record is None:
            raise KeyError(capture_id)
        if record.state is not LocalCaptureState.DONE:
            raise CaptureStorageError("只有中心最终确认的任务可进入 confirmed")
        source = self.pending / capture_id
        destination = self.confirmed / capture_id
        if destination.exists():
            return destination
        if not source.exists():
            raise CaptureStorageError(f"待确认目录不存在：{capture_id}")
        os.replace(source, destination)
        self._sync_directory(self.confirmed)
        return destination

    def cleanup_confirmed(
        self,
        *,
        confirmed_before: float,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        if not self.queue.cleanup_enabled:
            raise CaptureStorageError("完整性恢复后尚未完成中心对账，禁止清理")
        audit: list[dict[str, object]] = []
        for record in self.queue.find_cleanup_candidates(
            confirmed_before=confirmed_before,
            limit=limit,
        ):
            directory = self.confirmed / record.capture_id
            if not directory.exists():
                existing_audit = self.queue.get_cleanup_audit(record.capture_id)
                if existing_audit is not None and existing_audit["completed_at"] is None:
                    self.queue.finish_cleanup_audit(record.capture_id)
                continue
            try:
                persisted = self._read_persisted(directory)
                manifest = self._read_manifest(directory)
                self._create_queue_record(
                    manifest=manifest,
                    manifest_path=persisted.manifest_path,
                    images=list(persisted.images),
                )
            except BaseException as error:
                self._quarantine_path(
                    directory,
                    "pre-cleanup-integrity-invalid",
                )
                self._record_integrity_failure(record.capture_id)
                raise CaptureStorageError(
                    "清理前完整性复核失败，文件已隔离且自动清理已禁用"
                ) from error
            images = self.queue.list_images(record.capture_id)
            central_status = record.central_status
            if central_status not in {"FINALIZED", "FAILED"}:
                raise CaptureStorageError("清理候选缺少中心最终回执")
            sha256 = [image.sha256 for image in images]
            self.queue.begin_cleanup_audit(
                capture_id=record.capture_id,
                reason="CONFIRMED_RETENTION_EXPIRED",
                central_status=central_status,
                sha256=sha256,
            )
            shutil.rmtree(directory)
            self._sync_directory(self.confirmed)
            self.queue.finish_cleanup_audit(record.capture_id)
            audit.append(
                {
                    "capture_id": record.capture_id,
                    "reason": "CONFIRMED_RETENTION_EXPIRED",
                    "central_status": central_status,
                    "sha256": sha256,
                }
            )
        return audit

    def cleanup_by_retention(
        self,
        *,
        now: float,
        retention_seconds: float = 7 * 24 * 60 * 60,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        if retention_seconds < 0:
            raise ValueError("保留时间不能为负数")
        return self.cleanup_confirmed(
            confirmed_before=now - retention_seconds,
            limit=limit,
        )

    def disk_action(
        self,
        *,
        usage_ratio: float,
        warning_ratio: float,
        high_ratio: float,
        critical_ratio: float,
    ) -> str:
        thresholds = (warning_ratio, high_ratio, critical_ratio)
        if not 0 < thresholds[0] < thresholds[1] < thresholds[2] < 1:
            raise ValueError("磁盘阈值必须递增且位于 0 到 1")
        if usage_ratio >= critical_ratio:
            return "PAUSE_CAPTURE"
        if usage_ratio >= high_ratio:
            return "ACCELERATE_CONFIRMED_CLEANUP"
        if usage_ratio >= warning_ratio:
            return "WARN"
        return "NORMAL"

    def _create_queue_record(
        self,
        *,
        manifest: dict[str, object],
        manifest_path: Path,
        images: list[PersistedImage],
    ) -> None:
        trigger = manifest["trigger"]
        quality = manifest["quality"]
        if not isinstance(trigger, dict) or not isinstance(quality, dict):
            raise CaptureStorageError("清单触发或质量字段无效")
        capture_id = str(manifest["capture_id"])
        trigger_id = str(trigger["trigger_id"])
        trigger_source = str(trigger["source"])
        existing_trigger = self.queue.get_trigger(
            source=trigger_source,
            trigger_id=trigger_id,
        )
        if (
            existing_trigger is not None
            and existing_trigger["capture_id"] != capture_id
        ):
            raise QueueIntegrityError(
                "同一 trigger_id 已绑定不同 capture_id"
            )
        self.queue.create_capture(
            capture_id=capture_id,
            station_id=str(manifest["station_id"]),
            recipe_id=str(manifest["recipe_id"]),
            client_sequence=int(trigger["client_sequence"]),
            trigger_id=str(trigger["trigger_id"]),
            trigger_source=str(trigger["source"]),
            occurred_at=str(trigger["occurred_at"]),
            quality_status=str(quality["status"]),
            quality_warnings=tuple(str(item) for item in quality["warnings"]),
            manifest_path=manifest_path,
            images=[
                LocalImageRecord(
                    capture_id=capture_id,
                    image_role=image.image_role,
                    relative_path=image.relative_path,
                    sha256=image.sha256,
                    size_bytes=image.size_bytes,
                    width=image.width,
                    height=image.height,
                    media_type=image.media_type,
                    upload_status="PENDING",
                    central_image_id=None,
                )
                for image in images
            ],
        )
        warnings = tuple(str(item) for item in quality["warnings"])
        outcome_status = (
            "OK"
            if str(quality["status"]) == "OK"
            else f"QUALITY_{quality['status']}"
        )
        claimed = self.queue.claim_trigger(
            source=trigger_source,
            trigger_id=trigger_id,
            sequence=int(trigger["client_sequence"]),
            occurred_at=str(trigger["occurred_at"]),
            occurred_monotonic=0.0,
            capture_id=capture_id,
            outcome_status=outcome_status,
            warnings=warnings,
        )
        if not claimed:
            existing_trigger = self.queue.get_trigger(
                source=trigger_source,
                trigger_id=trigger_id,
            )
            if (
                existing_trigger is not None
                and existing_trigger["capture_id"] == capture_id
                and existing_trigger["outcome_status"] == "CAPTURE_STARTED"
            ):
                self.queue.finish_trigger(
                    source=trigger_source,
                    trigger_id=trigger_id,
                    outcome_status=outcome_status,
                    warnings=warnings,
                )

    def _read_persisted(self, directory: Path) -> PersistedCapture:
        manifest = self._read_manifest(directory)
        capture_id = str(manifest["capture_id"])
        directory_capture_id = (
            directory.name[:-4]
            if directory.parent == self.staging and directory.name.endswith(".tmp")
            else directory.name
        )
        if directory_capture_id != capture_id:
            raise CaptureStorageError("目录名与 capture_id 不一致")
        images: list[PersistedImage] = []
        for raw_image in manifest["images"]:
            relative_path = Path(str(raw_image["relative_path"]))
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise CaptureStorageError("清单包含越界路径")
            expected_prefix = Path("pending") / capture_id
            if relative_path.parent != expected_prefix:
                raise CaptureStorageError("清单路径不属于当前任务")
            file_path = directory / relative_path.name
            content = file_path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if digest != raw_image["sha256"] or len(content) != raw_image["size_bytes"]:
                raise CaptureStorageError("图片哈希或大小不一致")
            images.append(
                PersistedImage(
                    image_role=str(raw_image["image_role"]),
                    relative_path=relative_path,
                    sha256=digest,
                    size_bytes=len(content),
                    media_type=str(raw_image["media_type"]),
                    width=(
                        int(raw_image["width"])
                    ),
                    height=(
                        int(raw_image["height"])
                    ),
                )
            )
        quality_raw = manifest["quality"]
        return PersistedCapture(
            capture_id=capture_id,
            directory=directory,
            manifest_path=Path("pending") / capture_id / "manifest.json",
            images=tuple(images),
            quality=FrameQuality(
                status=str(quality_raw["status"]),
                warnings=tuple(str(item) for item in quality_raw["warnings"]),
            ),
        )

    @staticmethod
    def _read_manifest(directory: Path) -> dict[str, object]:
        manifest_path = directory / "manifest.json"
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise CaptureStorageError("清单版本不兼容")
        required = {
            "schema_version",
            "capture_id",
            "station_id",
            "recipe_id",
            "trigger",
            "quality",
            "images",
        }
        if set(raw) != required:
            raise CaptureStorageError("清单字段不完整或包含未知字段")
        if not isinstance(raw.get("images"), list) or not raw["images"]:
            raise CaptureStorageError("清单缺少图片")
        if len(raw["images"]) > 16:
            raise CaptureStorageError("清单图片数量超过冻结契约")
        roles: list[str] = []
        expected_image_fields = {
            "client_image_id",
            "image_role",
            "file_name",
            "relative_path",
            "sha256",
            "size_bytes",
            "media_type",
            "width",
            "height",
        }
        for image in raw["images"]:
            if not isinstance(image, dict) or set(image) != expected_image_fields:
                raise CaptureStorageError("清单图片字段无效")
            role = image.get("image_role")
            if (
                not isinstance(role, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", role)
                is None
            ):
                raise CaptureStorageError("清单 image_role 不是安全路径片段")
            roles.append(role.casefold())
            if image.get("client_image_id") != role.lower():
                raise CaptureStorageError("清单 client_image_id 与角色不一致")
            file_name = image.get("file_name")
            if (
                not isinstance(file_name, str)
                or Path(file_name).name != file_name
                or file_name in {".", ".."}
            ):
                raise CaptureStorageError("清单文件名不是安全路径片段")
        if len(roles) != len(set(roles)):
            raise CaptureStorageError("清单 image_role 大小写归一后重复")
        return raw

    def _record_integrity_failure(self, capture_id: str) -> None:
        self.queue.set_cleanup_enabled(False)
        self.queue.set_agent_state(
            f"integrity_incident:{capture_id}",
            {
                "error_code": "TD-EDGE-INTEGRITY-003",
                "requires_center_reconciliation": True,
            },
        )
        record = self.queue.get_capture(capture_id)
        if record is not None and record.state not in {
            LocalCaptureState.DONE,
            LocalCaptureState.LOCAL_DEAD,
        }:
            self.queue.transition(
                capture_id,
                LocalCaptureState.LOCAL_DEAD,
                error_code="TD-EDGE-INTEGRITY-003",
            )

    def _quarantine_path(self, path: Path, reason: str) -> None:
        destination = self.quarantine / f"{path.name}.{reason}"
        suffix = 1
        while destination.exists():
            destination = self.quarantine / f"{path.name}.{reason}.{suffix}"
            suffix += 1
        os.replace(path, destination)
        self._sync_directory(self.quarantine)

    def _crash(self, stage: str) -> None:
        if self.crash_hook is not None:
            self.crash_hook(stage)

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
