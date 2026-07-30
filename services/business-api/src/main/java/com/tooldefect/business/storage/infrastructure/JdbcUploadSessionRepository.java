package com.tooldefect.business.storage.infrastructure;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.storage.application.UploadSessionRepository;
import com.tooldefect.business.storage.domain.UploadSession;
import com.tooldefect.business.storage.domain.UploadSessionStatus;

@Repository
public class JdbcUploadSessionRepository implements UploadSessionRepository {
    private final JdbcTemplate jdbc;

    public JdbcUploadSessionRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<UploadSession> findLatest(UUID imageId) {
        return findLatest(imageId, false);
    }

    @Override
    public Optional<UploadSession> findLatestForUpdate(UUID imageId) {
        return findLatest(imageId, true);
    }

    private Optional<UploadSession> findLatest(UUID imageId, boolean forUpdate) {
        return jdbc.query(
            """
            SELECT upload_session_id,
                   image_id,
                   capture_id,
                   station_id,
                   receipt_sha256,
                   expected_size_bytes,
                   expected_sha256,
                   expected_media_type,
                   status,
                   expires_at
            FROM upload_session
            WHERE image_id = ?
            ORDER BY created_at DESC, upload_session_id DESC
            LIMIT 1
            """ + (forUpdate ? " FOR UPDATE" : ""),
            (result, row) -> new UploadSession(
                result.getObject("upload_session_id", UUID.class),
                result.getObject("image_id", UUID.class),
                result.getObject("capture_id", UUID.class),
                result.getObject("station_id", UUID.class),
                result.getString("receipt_sha256").trim(),
                result.getLong("expected_size_bytes"),
                result.getString("expected_sha256").trim(),
                result.getString("expected_media_type"),
                UploadSessionStatus.valueOf(result.getString("status")),
                result.getTimestamp("expires_at").toInstant()
            ),
            imageId
        ).stream().findFirst();
    }

    @Override
    public long countFailed(UUID imageId) {
        Long count = jdbc.queryForObject(
            """
            SELECT COUNT(*)
            FROM upload_session
            WHERE image_id = ?
              AND status = 'FAILED'
            """,
            Long.class,
            imageId
        );
        return count == null ? 0 : count;
    }

    @Override
    public void revokeIssued(UUID imageId, String reason) {
        jdbc.update(
            """
            UPDATE upload_session
            SET status = 'REVOKED',
                failure_code = ?
            WHERE image_id = ?
              AND status = 'ISSUED'
            """,
            reason,
            imageId
        );
    }

    @Override
    public void insert(UploadSession session) {
        jdbc.update(
            """
            INSERT INTO upload_session(
                upload_session_id,
                image_id,
                capture_id,
                station_id,
                receipt_sha256,
                expected_size_bytes,
                expected_sha256,
                expected_media_type,
                status,
                expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            session.uploadSessionId(),
            session.imageId(),
            session.captureId(),
            session.stationId(),
            session.receiptSha256(),
            session.expectedSizeBytes(),
            session.expectedSha256(),
            session.expectedMediaType(),
            session.status().name(),
            java.sql.Timestamp.from(session.expiresAt())
        );
    }

    @Override
    public boolean markConfirmed(UUID uploadSessionId, Instant confirmedAt) {
        return jdbc.update(
            """
            UPDATE upload_session
            SET status = 'CONFIRMED',
                confirmed_at = ?,
                failure_code = NULL
            WHERE upload_session_id = ?
              AND status = 'ISSUED'
            """,
            java.sql.Timestamp.from(confirmedAt),
            uploadSessionId
        ) == 1;
    }

    @Override
    public boolean markExpired(UUID uploadSessionId) {
        return jdbc.update(
            """
            UPDATE upload_session
            SET status = 'EXPIRED',
                failure_code = 'TICKET_EXPIRED'
            WHERE upload_session_id = ?
              AND status = 'ISSUED'
            """,
            uploadSessionId
        ) == 1;
    }

    @Override
    public boolean markFailed(UUID uploadSessionId, String failureCode) {
        return jdbc.update(
            """
            UPDATE upload_session
            SET status = 'FAILED',
                confirmed_at = NULL,
                failure_code = ?
            WHERE upload_session_id = ?
              AND status IN ('ISSUED', 'CONFIRMED')
            """,
            failureCode,
            uploadSessionId
        ) == 1;
    }
}
