package com.tooldefect.business.shared.infrastructure;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.shared.application.InboxRepository;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.messaging.InboxReceipt;
import com.tooldefect.business.shared.messaging.InboxStatus;

@Repository
public class JdbcInboxRepository implements InboxRepository {
    private final JdbcTemplate jdbc;

    public JdbcInboxRepository(JdbcTemplate jdbc) {
        this.jdbc = Objects.requireNonNull(jdbc);
    }

    @Override
    public Claim claim(
            String messageId,
            String consumer,
            UUID detectionTaskId,
            String resultSha256,
            String claimOwner,
            Instant now,
            Duration leaseDuration) {
        jdbc.update("""
            INSERT INTO inbox_message (
                message_id,
                consumer,
                detection_task_id,
                status,
                result_sha256,
                received_at
            )
            VALUES (?, ?, ?, 'FAILED', ?, ?)
            ON CONFLICT DO NOTHING
            """,
            messageId,
            consumer,
            detectionTaskId,
            resultSha256,
            Timestamp.from(now)
        );

        List<InboxReceipt> matching = jdbc.query("""
            SELECT
                message_id,
                consumer,
                detection_task_id,
                result_sha256,
                status,
                claim_owner,
                lease_until,
                attempt_count,
                received_at,
                processed_at,
                last_error
            FROM inbox_message
            WHERE consumer = ?
              AND (message_id = ? OR detection_task_id = ?)
            ORDER BY message_id
            FOR UPDATE
            """,
            JdbcInboxRepository::mapReceipt,
            consumer,
            messageId,
            detectionTaskId
        );
        if (matching.size() != 1) {
            throw new DomainViolation("message_id 与 detection_task_id 映射冲突");
        }
        InboxReceipt current = matching.getFirst();
        if (!current.detectionTaskId().equals(detectionTaskId)
                || !Objects.equals(current.resultSha256(), resultSha256)) {
            throw new DomainViolation("重复消息的任务或结果哈希不一致");
        }
        if (current.status() == InboxStatus.PROCESSED) {
            return new Claim(Decision.ALREADY_PROCESSED, current);
        }
        if (current.status() == InboxStatus.PROCESSING
                && current.leaseUntil().isAfter(now)) {
            return new Claim(Decision.BUSY, current);
        }

        Instant leaseUntil = now.plus(leaseDuration);
        int updated = jdbc.update("""
            UPDATE inbox_message
            SET status = 'PROCESSING',
                claim_owner = ?,
                lease_until = ?,
                attempt_count = attempt_count + 1,
                last_error = NULL
            WHERE message_id = ?
              AND consumer = ?
              AND (
                  status = 'FAILED'
                  OR (status = 'PROCESSING' AND lease_until <= ?)
              )
            """,
            claimOwner,
            Timestamp.from(leaseUntil),
            current.messageId(),
            current.consumer(),
            Timestamp.from(now)
        );
        if (updated != 1) {
            return new Claim(Decision.BUSY, current);
        }
        InboxReceipt claimed = new InboxReceipt(
            current.messageId(),
            current.consumer(),
            current.detectionTaskId(),
            current.resultSha256(),
            InboxStatus.PROCESSING,
            claimOwner,
            leaseUntil,
            current.attemptCount() + 1,
            current.receivedAt(),
            null,
            null
        );
        return new Claim(Decision.PROCESS, claimed);
    }

    @Override
    public boolean markProcessed(
            String messageId,
            String consumer,
            String claimOwner,
            Instant processedAt) {
        return jdbc.update("""
            UPDATE inbox_message
            SET status = 'PROCESSED',
                processed_at = ?,
                claim_owner = NULL,
                lease_until = NULL,
                last_error = NULL
            WHERE message_id = ?
              AND consumer = ?
              AND status = 'PROCESSING'
              AND claim_owner = ?
            """,
            Timestamp.from(processedAt),
            messageId,
            consumer,
            claimOwner
        ) == 1;
    }

    private static InboxReceipt mapReceipt(ResultSet row, int rowNumber)
            throws SQLException {
        return new InboxReceipt(
            row.getString("message_id"),
            row.getString("consumer"),
            row.getObject("detection_task_id", UUID.class),
            row.getString("result_sha256"),
            InboxStatus.valueOf(row.getString("status")),
            row.getString("claim_owner"),
            nullableInstant(row, "lease_until"),
            row.getInt("attempt_count"),
            row.getTimestamp("received_at").toInstant(),
            nullableInstant(row, "processed_at"),
            row.getString("last_error")
        );
    }

    private static Instant nullableInstant(ResultSet row, String column)
            throws SQLException {
        Timestamp value = row.getTimestamp(column);
        return value == null ? null : value.toInstant();
    }
}
