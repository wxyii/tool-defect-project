package com.tooldefect.business.shared.infrastructure;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.shared.application.OutboxRepository;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.messaging.OutboxEvent;
import com.tooldefect.business.shared.messaging.OutboxStatus;

@Repository
public class JdbcOutboxRepository implements OutboxRepository {
    private static final String RETURNING_COLUMNS = """
        o.event_id,
        o.aggregate_type,
        o.aggregate_id,
        o.event_type,
        o.routing_key,
        o.payload::text AS payload_json,
        o.status,
        o.attempt_count,
        o.next_attempt_at,
        o.created_at,
        o.published_at,
        o.claim_owner,
        o.lease_until,
        o.last_error
        """;

    private final JdbcTemplate jdbc;

    public JdbcOutboxRepository(JdbcTemplate jdbc) {
        this.jdbc = java.util.Objects.requireNonNull(jdbc);
    }

    @Override
    public void append(OutboxEvent event) {
        if (event.status() != OutboxStatus.NEW) {
            throw new DomainViolation("只能追加 NEW 发件箱事件");
        }
        int inserted = jdbc.update("""
            INSERT INTO outbox_event (
                event_id,
                aggregate_type,
                aggregate_id,
                event_type,
                routing_key,
                payload,
                status,
                attempt_count,
                next_attempt_at,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, CAST(? AS jsonb), 'NEW', 0, ?, ?)
            """,
            event.eventId(),
            event.aggregateType(),
            event.aggregateId(),
            event.eventType(),
            event.routingKey(),
            event.payloadJson(),
            Timestamp.from(event.nextAttemptAt()),
            Timestamp.from(event.createdAt())
        );
        if (inserted != 1) {
            throw new DomainViolation("发件箱事件追加失败");
        }
    }

    @Override
    public List<OutboxEvent> claimBatch(
            Instant now,
            int limit,
            String claimOwner,
            Duration leaseDuration) {
        Instant leaseUntil = now.plus(leaseDuration);
        return jdbc.query("""
            WITH candidates AS (
                SELECT event_id
                FROM outbox_event
                WHERE (
                    status IN ('NEW', 'FAILED')
                    AND next_attempt_at <= ?
                ) OR (
                    status = 'CLAIMED'
                    AND lease_until <= ?
                )
                ORDER BY created_at, event_id
                FOR UPDATE SKIP LOCKED
                LIMIT ?
            )
            UPDATE outbox_event AS o
            SET status = 'CLAIMED',
                claim_owner = ?,
                lease_until = ?,
                attempt_count = o.attempt_count + 1,
                last_error = NULL
            FROM candidates AS c
            WHERE o.event_id = c.event_id
            RETURNING
            """ + RETURNING_COLUMNS,
            JdbcOutboxRepository::mapEvent,
            Timestamp.from(now),
            Timestamp.from(now),
            limit,
            claimOwner,
            Timestamp.from(leaseUntil)
        );
    }

    @Override
    public boolean markPublished(
            UUID eventId,
            String claimOwner,
            Instant publishedAt) {
        return jdbc.update("""
            UPDATE outbox_event
            SET status = 'PUBLISHED',
                published_at = ?,
                claim_owner = NULL,
                lease_until = NULL,
                last_error = NULL
            WHERE event_id = ?
              AND status = 'CLAIMED'
              AND claim_owner = ?
            """,
            Timestamp.from(publishedAt),
            eventId,
            claimOwner
        ) == 1;
    }

    @Override
    public boolean markFailed(
            UUID eventId,
            String claimOwner,
            Instant retryAt,
            String errorSummary) {
        return jdbc.update("""
            UPDATE outbox_event
            SET status = 'FAILED',
                next_attempt_at = ?,
                claim_owner = NULL,
                lease_until = NULL,
                last_error = ?
            WHERE event_id = ?
              AND status = 'CLAIMED'
              AND claim_owner = ?
            """,
            Timestamp.from(retryAt),
            errorSummary,
            eventId,
            claimOwner
        ) == 1;
    }

    @Override
    public boolean markDead(
            UUID eventId,
            String claimOwner,
            Instant failedAt,
            String errorSummary) {
        return jdbc.update("""
            UPDATE outbox_event
            SET status = 'DEAD',
                next_attempt_at = ?,
                claim_owner = NULL,
                lease_until = NULL,
                last_error = ?
            WHERE event_id = ?
              AND status = 'CLAIMED'
              AND claim_owner = ?
            """,
            Timestamp.from(failedAt),
            errorSummary,
            eventId,
            claimOwner
        ) == 1;
    }

    @Override
    public boolean exists(UUID eventId) {
        Integer count = jdbc.queryForObject(
            "SELECT COUNT(*) FROM outbox_event WHERE event_id = ?",
            Integer.class,
            eventId
        );
        return count != null && count == 1;
    }

    private static OutboxEvent mapEvent(ResultSet row, int rowNumber)
            throws SQLException {
        return new OutboxEvent(
            row.getObject("event_id", UUID.class),
            row.getString("aggregate_type"),
            row.getObject("aggregate_id", UUID.class),
            row.getString("event_type"),
            row.getString("routing_key"),
            row.getString("payload_json"),
            OutboxStatus.valueOf(row.getString("status")),
            row.getInt("attempt_count"),
            row.getTimestamp("next_attempt_at").toInstant(),
            row.getTimestamp("created_at").toInstant(),
            nullableInstant(row, "published_at"),
            row.getString("claim_owner"),
            nullableInstant(row, "lease_until"),
            row.getString("last_error")
        );
    }

    private static Instant nullableInstant(ResultSet row, String column)
            throws SQLException {
        Timestamp value = row.getTimestamp(column);
        return value == null ? null : value.toInstant();
    }
}
