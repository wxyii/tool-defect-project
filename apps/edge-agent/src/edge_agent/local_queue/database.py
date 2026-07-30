"""SQLite WAL 本地队列。

数据库只保存同步所需事实；最终业务处置始终来自中心。
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
from typing import Iterable, Iterator, Optional, Sequence

from .models import (
    CaptureRecord,
    LocalCaptureState,
    LocalImageRecord,
    can_transition,
)


class QueueIntegrityError(RuntimeError):
    """本地数据库或状态约束损坏。"""


class EdgeQueue:
    """线程外部串行使用的 SQLite 队列。"""

    def __init__(
        self,
        database_path: Path | str,
        *,
        migrations_dir: Path | str | None = None,
        busy_timeout_ms: int = 5_000,
        clock=time.time,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._connection = sqlite3.connect(
            self.database_path,
            timeout=busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        try:
            journal_row = self._connection.execute(
                "PRAGMA journal_mode = WAL"
            ).fetchone()
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                f"PRAGMA busy_timeout = {int(busy_timeout_ms)}"
            )
            actual_journal = (
                str(journal_row[0]).lower() if journal_row is not None else ""
            )
            actual_foreign_keys = int(
                self._connection.execute("PRAGMA foreign_keys").fetchone()[0]
            )
            actual_busy_timeout = int(
                self._connection.execute("PRAGMA busy_timeout").fetchone()[0]
            )
            if actual_journal != "wal":
                raise QueueIntegrityError(
                    f"SQLite 未能启用 WAL，实际为 {actual_journal or '未知'}"
                )
            if actual_foreign_keys != 1:
                raise QueueIntegrityError("SQLite 未能启用外键约束")
            if actual_busy_timeout < int(busy_timeout_ms):
                raise QueueIntegrityError(
                    "SQLite busy_timeout 低于配置要求"
                )
            if migrations_dir is None:
                migrations_dir = Path(__file__).resolve().parents[3] / "migrations"
            self._migrate(Path(migrations_dir))
            self.integrity_check()
        except BaseException:
            self._connection.close()
            raise

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "EdgeQueue":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield self._connection
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")

    def _migrate(self, migrations_dir: Path) -> None:
        migration_files = sorted(migrations_dir.glob("*.sql"))
        if not migration_files:
            raise FileNotFoundError(f"未找到 SQLite 迁移：{migrations_dir}")
        with self.transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migration (
                    version TEXT PRIMARY KEY,
                    applied_at REAL NOT NULL
                )
                """
            )
        for migration in migration_files:
            version = migration.stem.split("_", 1)[0]
            existing = self._connection.execute(
                "SELECT 1 FROM schema_migration WHERE version = ?", (version,)
            ).fetchone()
            if existing:
                continue
            script = migration.read_text(encoding="utf-8")
            # executescript 自身管理事务；迁移必须幂等，应用记录紧随其后。
            self._connection.executescript(script)
            self._connection.execute(
                "INSERT INTO schema_migration(version, applied_at) VALUES (?, ?)",
                (version, self._clock()),
            )

    @property
    def journal_mode(self) -> str:
        row = self._connection.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]).lower()

    @property
    def foreign_keys_enabled(self) -> bool:
        row = self._connection.execute("PRAGMA foreign_keys").fetchone()
        return bool(row[0])

    @property
    def busy_timeout_ms(self) -> int:
        row = self._connection.execute("PRAGMA busy_timeout").fetchone()
        return int(row[0])

    def integrity_check(self) -> None:
        rows = self._connection.execute("PRAGMA integrity_check").fetchall()
        messages = [str(row[0]) for row in rows]
        if messages != ["ok"]:
            raise QueueIntegrityError("; ".join(messages))

    def create_capture(
        self,
        *,
        capture_id: str,
        station_id: str,
        recipe_id: str,
        client_sequence: int,
        trigger_id: str,
        trigger_source: str,
        occurred_at: str,
        quality_status: str,
        quality_warnings: Sequence[str],
        manifest_path: Path | str,
        images: Sequence[LocalImageRecord],
    ) -> bool:
        """以 `capture_id` 幂等创建本地任务。

        相同标识但元数据不同会拒绝，避免覆盖首次采集。
        """

        now = self._clock()
        manifest_text = Path(manifest_path).as_posix()
        for image in images:
            if image.capture_id != capture_id:
                raise QueueIntegrityError("图片 capture_id 与任务不一致")
            if (
                image.relative_path.is_absolute()
                or ".." in image.relative_path.parts
            ):
                raise QueueIntegrityError("本地图片路径必须为安全相对路径")
        with self.transaction() as connection:
            existing = connection.execute(
                """
                SELECT station_id, recipe_id, client_sequence, trigger_id,
                       trigger_source, occurred_at, quality_status,
                       quality_warnings_json, manifest_path
                FROM capture_queue WHERE capture_id = ?
                """,
                (capture_id,),
            ).fetchone()
            if existing:
                existing_images = connection.execute(
                    """
                    SELECT image_role, relative_path, sha256, size_bytes,
                           width, height, media_type
                    FROM local_image
                    WHERE capture_id = ?
                    ORDER BY image_role
                    """,
                    (capture_id,),
                ).fetchall()
                expected_images = sorted(
                    (
                        image.image_role,
                        image.relative_path.as_posix(),
                        image.sha256,
                        image.size_bytes,
                        image.width,
                        image.height,
                        image.media_type,
                    )
                    for image in images
                )
                actual_images = [
                    (
                        str(row["image_role"]),
                        str(row["relative_path"]),
                        str(row["sha256"]),
                        int(row["size_bytes"]),
                        int(row["width"]),
                        int(row["height"]),
                        str(row["media_type"]),
                    )
                    for row in existing_images
                ]
                if (
                    str(existing["station_id"]) != station_id
                    or str(existing["recipe_id"]) != recipe_id
                    or int(existing["client_sequence"]) != client_sequence
                    or str(existing["trigger_id"]) != trigger_id
                    or str(existing["trigger_source"]) != trigger_source
                    or str(existing["occurred_at"]) != occurred_at
                    or str(existing["quality_status"]) != quality_status
                    or json.loads(str(existing["quality_warnings_json"]))
                    != list(quality_warnings)
                    or str(existing["manifest_path"]) != manifest_text
                    or actual_images != expected_images
                ):
                    raise QueueIntegrityError(
                        f"capture_id {capture_id} 的幂等内容不一致"
                    )
                return False
            connection.execute(
                """
                INSERT INTO capture_queue(
                    capture_id, station_id, recipe_id, client_sequence,
                    trigger_id, trigger_source, occurred_at,
                    quality_status, quality_warnings_json,
                    state, manifest_path,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
                """,
                (
                    capture_id,
                    station_id,
                    recipe_id,
                    client_sequence,
                    trigger_id,
                    trigger_source,
                    occurred_at,
                    quality_status,
                    json.dumps(
                        list(quality_warnings),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    manifest_text,
                    now,
                    now,
                ),
            )
            for image in images:
                connection.execute(
                    """
                    INSERT INTO local_image(
                        capture_id, image_role, relative_path, sha256,
                        size_bytes, width, height, media_type,
                        upload_status, central_image_id, upload_receipt
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        capture_id,
                        image.image_role,
                        image.relative_path.as_posix(),
                        image.sha256,
                        image.size_bytes,
                        image.width,
                        image.height,
                        image.media_type,
                        image.upload_status,
                        image.central_image_id,
                        image.upload_receipt,
                    ),
                )
        return True

    def get_capture(self, capture_id: str) -> Optional[CaptureRecord]:
        row = self._connection.execute(
            "SELECT * FROM capture_queue WHERE capture_id = ?", (capture_id,)
        ).fetchone()
        return self._capture_from_row(row) if row else None

    def list_images(self, capture_id: str) -> list[LocalImageRecord]:
        rows = self._connection.execute(
            """
            SELECT * FROM local_image
            WHERE capture_id = ? ORDER BY image_role
            """,
            (capture_id,),
        ).fetchall()
        return [
            LocalImageRecord(
                capture_id=str(row["capture_id"]),
                image_role=str(row["image_role"]),
                relative_path=Path(str(row["relative_path"])),
                sha256=str(row["sha256"]),
                size_bytes=int(row["size_bytes"]),
                width=int(row["width"]) if row["width"] is not None else None,
                height=int(row["height"]) if row["height"] is not None else None,
                media_type=str(row["media_type"]),
                upload_status=str(row["upload_status"]),
                central_image_id=(
                    str(row["central_image_id"])
                    if row["central_image_id"] is not None
                    else None
                ),
                upload_receipt=(
                    str(row["upload_receipt"])
                    if row["upload_receipt"] is not None
                    else None
                ),
            )
            for row in rows
        ]

    def transition(
        self,
        capture_id: str,
        target: LocalCaptureState,
        *,
        expected: Optional[LocalCaptureState] = None,
        central_status: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> CaptureRecord:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM capture_queue WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
            if row is None:
                raise KeyError(capture_id)
            current = LocalCaptureState(str(row["state"]))
            if expected is not None and current is not expected:
                raise QueueIntegrityError(
                    f"{capture_id} 当前状态 {current.value}，预期 {expected.value}"
                )
            resume_state = (
                LocalCaptureState(str(row["resume_state"]))
                if row["resume_state"]
                else None
            )
            if not can_transition(current, target, retry_resume_state=resume_state):
                raise QueueIntegrityError(
                    f"非法本地状态转换：{current.value} -> {target.value}"
                )
            now = self._clock()
            confirmed_at = row["confirmed_at"]
            if target is LocalCaptureState.DONE:
                if central_status not in {"FINALIZED", "FAILED"}:
                    raise QueueIntegrityError("DONE 必须携带中心最终状态")
                confirmed_at = now
            connection.execute(
                """
                UPDATE capture_queue
                SET state = ?, updated_at = ?, retry_at = NULL,
                    resume_state = NULL,
                    next_poll_at = CASE WHEN ? = 'DONE' THEN NULL ELSE next_poll_at END,
                    central_status = COALESCE(?, central_status),
                    error_code = ?,
                    confirmed_at = ?
                WHERE capture_id = ?
                """,
                (
                    target.value,
                    now,
                    target.value,
                    central_status,
                    error_code,
                    confirmed_at,
                    capture_id,
                ),
            )
        result = self.get_capture(capture_id)
        assert result is not None
        return result

    def defer_poll(self, capture_id: str, *, next_poll_at: float) -> CaptureRecord:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT state FROM capture_queue WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
            if row is None:
                raise KeyError(capture_id)
            if LocalCaptureState(str(row["state"])) is not LocalCaptureState.WAIT_RESULT:
                raise QueueIntegrityError("只有 WAIT_RESULT 可设置下次轮询时间")
            connection.execute(
                """
                UPDATE capture_queue
                SET next_poll_at = ?, updated_at = ?
                WHERE capture_id = ?
                """,
                (next_poll_at, self._clock(), capture_id),
            )
        result = self.get_capture(capture_id)
        assert result is not None
        return result

    def schedule_retry(
        self,
        capture_id: str,
        *,
        retry_at: float,
        error_code: str,
    ) -> CaptureRecord:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT state, retry_count FROM capture_queue WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
            if row is None:
                raise KeyError(capture_id)
            current = LocalCaptureState(str(row["state"]))
            if current in {LocalCaptureState.DONE, LocalCaptureState.LOCAL_DEAD}:
                raise QueueIntegrityError(f"{current.value} 不能进入重试")
            resume_state = (
                str(row["state"])
                if current is not LocalCaptureState.RETRY_WAIT
                else None
            )
            connection.execute(
                """
                UPDATE capture_queue
                SET state = 'RETRY_WAIT',
                    retry_count = retry_count + 1,
                    retry_at = ?,
                    resume_state = COALESCE(?, resume_state),
                    error_code = ?,
                    updated_at = ?
                WHERE capture_id = ?
                """,
                (retry_at, resume_state, error_code, self._clock(), capture_id),
            )
        result = self.get_capture(capture_id)
        assert result is not None
        return result

    def due_captures(
        self,
        *,
        now: Optional[float] = None,
        limit: int = 100,
    ) -> list[CaptureRecord]:
        current_time = self._clock() if now is None else now
        rows = self._connection.execute(
            """
            SELECT * FROM capture_queue
            WHERE state NOT IN ('DONE', 'LOCAL_DEAD')
              AND (state != 'RETRY_WAIT' OR retry_at <= ?)
              AND (state != 'WAIT_RESULT' OR next_poll_at IS NULL OR next_poll_at <= ?)
            ORDER BY created_at, capture_id
            LIMIT ?
            """,
            (current_time, current_time, limit),
        ).fetchall()
        return [self._capture_from_row(row) for row in rows]

    def unfinished_capture_ids(self, *, limit: int = 500) -> list[str]:
        rows = self._connection.execute(
            """
            SELECT capture_id FROM capture_queue
            WHERE state NOT IN ('DONE', 'LOCAL_DEAD')
            ORDER BY created_at, capture_id LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def update_image_upload(
        self,
        *,
        capture_id: str,
        image_role: str,
        status: str,
        central_image_id: Optional[str] = None,
        upload_receipt: Optional[str] = None,
    ) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE local_image
                SET upload_status = ?,
                    central_image_id = COALESCE(?, central_image_id),
                    upload_receipt = COALESCE(?, upload_receipt)
                WHERE capture_id = ? AND image_role = ?
                """,
                (
                    status,
                    central_image_id,
                    upload_receipt,
                    capture_id,
                    image_role,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError((capture_id, image_role))

    def invalidate_image_upload(
        self,
        *,
        capture_id: str,
        image_role: str,
    ) -> None:
        """使过期会话回到待上传，同时保留中心 image_id 以便续票。"""

        cursor = self._connection.execute(
            """
            UPDATE local_image
            SET upload_status = 'PENDING', upload_receipt = NULL
            WHERE capture_id = ? AND image_role = ?
            """,
            (capture_id, image_role),
        )
        if cursor.rowcount != 1:
            raise KeyError((capture_id, image_role))

    def record_sync_start(
        self,
        *,
        request_id: str,
        capture_id: str,
        operation: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO sync_attempt(
                request_id, capture_id, operation, started_at
            ) VALUES (?, ?, ?, ?)
            """,
            (request_id, capture_id, operation, self._clock()),
        )

    def record_sync_finish(
        self,
        *,
        request_id: str,
        result: str,
        error_code: Optional[str] = None,
    ) -> None:
        self._connection.execute(
            """
            UPDATE sync_attempt
            SET finished_at = ?, result = ?, error_code = ?
            WHERE request_id = ?
            """,
            (self._clock(), result, error_code, request_id),
        )

    def claim_trigger(
        self,
        *,
        source: str,
        trigger_id: str,
        sequence: int,
        occurred_at: str,
        occurred_monotonic: float,
        related_trigger_id: str | None = None,
        capture_id: str | None,
        outcome_status: str,
        warnings: Sequence[str] = (),
    ) -> bool:
        now = self._clock()
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO trigger_event(
                    source, trigger_id, sequence, occurred_at,
                    occurred_monotonic, related_trigger_id, capture_id,
                    outcome_status,
                    warnings_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    trigger_id,
                    sequence,
                    occurred_at,
                    occurred_monotonic,
                    related_trigger_id,
                    capture_id,
                    outcome_status,
                    json.dumps(list(warnings), separators=(",", ":")),
                    now,
                    now,
                ),
            )
        return cursor.rowcount == 1

    def finish_trigger(
        self,
        *,
        source: str,
        trigger_id: str,
        outcome_status: str,
        warnings: Sequence[str],
        error_code: str | None = None,
    ) -> None:
        cursor = self._connection.execute(
            """
            UPDATE trigger_event
            SET outcome_status = ?, warnings_json = ?, error_code = ?,
                updated_at = ?
            WHERE source = ? AND trigger_id = ?
            """,
            (
                outcome_status,
                json.dumps(list(warnings), separators=(",", ":")),
                error_code,
                self._clock(),
                source,
                trigger_id,
            ),
        )
        if cursor.rowcount != 1:
            raise KeyError((source, trigger_id))

    def get_trigger(self, *, source: str, trigger_id: str) -> dict[str, object] | None:
        row = self._connection.execute(
            """
            SELECT * FROM trigger_event
            WHERE source = ? AND trigger_id = ?
            """,
            (source, trigger_id),
        ).fetchone()
        return self._trigger_from_row(row) if row else None

    def latest_claimed_trigger(self, *, source: str) -> dict[str, object] | None:
        row = self._connection.execute(
            """
            SELECT * FROM trigger_event
            WHERE source = ? AND capture_id IS NOT NULL
            ORDER BY occurred_monotonic DESC, created_at DESC
            LIMIT 1
            """,
            (source,),
        ).fetchone()
        return self._trigger_from_row(row) if row else None

    def unfinished_triggers(self) -> list[dict[str, object]]:
        rows = self._connection.execute(
            """
            SELECT * FROM trigger_event
            WHERE outcome_status = 'CAPTURE_STARTED'
            ORDER BY created_at, source, trigger_id
            """
        ).fetchall()
        return [self._trigger_from_row(row) for row in rows]

    def queue_depth(self) -> int:
        row = self._connection.execute(
            """
            SELECT count(*) FROM capture_queue
            WHERE state NOT IN ('DONE', 'LOCAL_DEAD')
            """
        ).fetchone()
        return int(row[0])

    def oldest_unfinished_age_seconds(self, *, now: Optional[float] = None) -> float:
        current_time = self._clock() if now is None else now
        row = self._connection.execute(
            """
            SELECT min(created_at) FROM capture_queue
            WHERE state NOT IN ('DONE', 'LOCAL_DEAD')
            """
        ).fetchone()
        if row[0] is None:
            return 0.0
        return max(0.0, current_time - float(row[0]))

    def find_cleanup_candidates(
        self,
        *,
        confirmed_before: float,
        limit: int = 100,
    ) -> list[CaptureRecord]:
        rows = self._connection.execute(
            """
            SELECT * FROM capture_queue
            WHERE state = 'DONE'
              AND confirmed_at IS NOT NULL
              AND confirmed_at <= ?
            ORDER BY confirmed_at, capture_id LIMIT ?
            """,
            (confirmed_before, limit),
        ).fetchall()
        return [self._capture_from_row(row) for row in rows]

    def begin_cleanup_audit(
        self,
        *,
        capture_id: str,
        reason: str,
        central_status: str,
        sha256: Sequence[str],
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO cleanup_audit(
                capture_id, reason, central_status, sha256_json, requested_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(capture_id) DO NOTHING
            """,
            (
                capture_id,
                reason,
                central_status,
                json.dumps(list(sha256), separators=(",", ":")),
                self._clock(),
            ),
        )

    def finish_cleanup_audit(self, capture_id: str) -> None:
        cursor = self._connection.execute(
            """
            UPDATE cleanup_audit
            SET completed_at = COALESCE(completed_at, ?)
            WHERE capture_id = ?
            """,
            (self._clock(), capture_id),
        )
        if cursor.rowcount != 1:
            raise KeyError(capture_id)

    def get_cleanup_audit(self, capture_id: str) -> dict[str, object] | None:
        row = self._connection.execute(
            "SELECT * FROM cleanup_audit WHERE capture_id = ?",
            (capture_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "capture_id": str(row["capture_id"]),
            "reason": str(row["reason"]),
            "central_status": str(row["central_status"]),
            "sha256": tuple(json.loads(str(row["sha256_json"]))),
            "requested_at": float(row["requested_at"]),
            "completed_at": (
                float(row["completed_at"])
                if row["completed_at"] is not None
                else None
            ),
        }

    def set_agent_state(self, key: str, value: object) -> None:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        self._connection.execute(
            """
            INSERT INTO agent_state(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, encoded, self._clock()),
        )

    def get_agent_state(self, key: str) -> object | None:
        row = self._connection.execute(
            "SELECT value FROM agent_state WHERE key = ?", (key,)
        ).fetchone()
        return json.loads(str(row[0])) if row else None

    @property
    def cleanup_enabled(self) -> bool:
        value = self.get_agent_state("cleanup_enabled")
        return value is not False

    def set_cleanup_enabled(self, enabled: bool) -> None:
        self.set_agent_state("cleanup_enabled", bool(enabled))

    @staticmethod
    def _trigger_from_row(row: sqlite3.Row) -> dict[str, object]:
        return {
            "source": str(row["source"]),
            "trigger_id": str(row["trigger_id"]),
            "sequence": int(row["sequence"]),
            "occurred_at": str(row["occurred_at"]),
            "occurred_monotonic": float(row["occurred_monotonic"]),
            "related_trigger_id": (
                str(row["related_trigger_id"])
                if row["related_trigger_id"] is not None
                else None
            ),
            "capture_id": (
                str(row["capture_id"])
                if row["capture_id"] is not None
                else None
            ),
            "outcome_status": str(row["outcome_status"]),
            "warnings": tuple(json.loads(str(row["warnings_json"]))),
            "error_code": (
                str(row["error_code"])
                if row["error_code"] is not None
                else None
            ),
        }

    @staticmethod
    def _capture_from_row(row: sqlite3.Row) -> CaptureRecord:
        return CaptureRecord(
            capture_id=str(row["capture_id"]),
            station_id=str(row["station_id"]),
            recipe_id=str(row["recipe_id"]),
            client_sequence=int(row["client_sequence"]),
            trigger_id=str(row["trigger_id"]),
            trigger_source=str(row["trigger_source"]),
            occurred_at=str(row["occurred_at"]),
            quality_status=str(row["quality_status"]),
            quality_warnings=tuple(
                str(item)
                for item in json.loads(str(row["quality_warnings_json"]))
            ),
            state=LocalCaptureState(str(row["state"])),
            manifest_path=Path(str(row["manifest_path"])),
            retry_count=int(row["retry_count"]),
            retry_at=float(row["retry_at"]) if row["retry_at"] is not None else None,
            resume_state=(
                LocalCaptureState(str(row["resume_state"]))
                if row["resume_state"]
                else None
            ),
            next_poll_at=(
                float(row["next_poll_at"])
                if row["next_poll_at"] is not None
                else None
            ),
            central_status=(
                str(row["central_status"])
                if row["central_status"] is not None
                else None
            ),
            error_code=(
                str(row["error_code"]) if row["error_code"] is not None else None
            ),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            confirmed_at=(
                float(row["confirmed_at"])
                if row["confirmed_at"] is not None
                else None
            ),
        )
