"""SQLite 完整性失败的显式备份与目录重建流程。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import time
from typing import Callable

from ..capture.storage import AtomicCaptureStore
from .database import EdgeQueue, QueueIntegrityError


@dataclass(frozen=True)
class QueueOpenResult:
    queue: EdgeQueue
    recovered_capture_ids: tuple[str, ...] = ()
    quarantined_items: tuple[str, ...] = ()
    backup_paths: tuple[Path, ...] = ()
    center_reconciliation_required: bool = False


def open_queue_with_recovery(
    database_path: Path | str,
    *,
    data_root: Path | str,
    migrations_dir: Path | str | None = None,
    busy_timeout_ms: int = 5_000,
    clock: Callable[[], float] = time.time,
) -> QueueOpenResult:
    """打开并检查队列；损坏时备份文件、重建同步事实并冻结清理。"""

    path = Path(database_path)
    try:
        queue = EdgeQueue(
            path,
            migrations_dir=migrations_dir,
            busy_timeout_ms=busy_timeout_ms,
            clock=clock,
        )
        return QueueOpenResult(queue=queue)
    except (sqlite3.DatabaseError, QueueIntegrityError):
        if not path.exists():
            raise

    backup_paths = _backup_database_files(
        path,
        quarantine_root=Path(data_root) / "quarantine" / "database",
        timestamp=int(clock()),
    )
    queue = EdgeQueue(
        path,
        migrations_dir=migrations_dir,
        busy_timeout_ms=busy_timeout_ms,
        clock=clock,
    )
    queue.set_cleanup_enabled(False)
    recovered = AtomicCaptureStore(data_root, queue).recover()
    queue.set_agent_state(
        "integrity_recovery",
        {
            "backup_paths": [item.name for item in backup_paths],
            "recovered_capture_ids": recovered["recovered"],
            "quarantined_items": recovered["quarantined"],
            "center_reconciliation_required": True,
        },
    )
    return QueueOpenResult(
        queue=queue,
        recovered_capture_ids=tuple(recovered["recovered"]),
        quarantined_items=tuple(recovered["quarantined"]),
        backup_paths=backup_paths,
        center_reconciliation_required=True,
    )


def _backup_database_files(
    database_path: Path,
    *,
    quarantine_root: Path,
    timestamp: int,
) -> tuple[Path, ...]:
    quarantine_root.mkdir(parents=True, exist_ok=True)
    backups: list[Path] = []
    for source in (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ):
        if not source.exists():
            continue
        destination = quarantine_root / f"{source.name}.corrupt-{timestamp}"
        counter = 1
        while destination.exists():
            destination = (
                quarantine_root
                / f"{source.name}.corrupt-{timestamp}.{counter}"
            )
            counter += 1
        os.replace(source, destination)
        backups.append(destination)
    _sync_directory(quarantine_root)
    return tuple(backups)


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
