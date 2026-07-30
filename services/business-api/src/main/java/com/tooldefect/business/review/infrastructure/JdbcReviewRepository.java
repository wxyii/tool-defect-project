package com.tooldefect.business.review.infrastructure;

import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.review.application.ReviewRepository;
import com.tooldefect.business.review.application.ReviewSubmission;
import com.tooldefect.business.review.application.ReviewTaskState;
import com.tooldefect.business.review.domain.ReviewConflict;
import com.tooldefect.business.review.domain.ReviewNotFound;
import com.tooldefect.business.review.domain.ReviewStatus;
import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.domain.DomainViolation;

@Repository
public class JdbcReviewRepository implements ReviewRepository {
    private static final String AUTHORIZED_SCOPE = """
        EXISTS (
            SELECT 1
            FROM sys_user user_account
            JOIN sys_user_role user_role
              ON user_role.user_id = user_account.user_id
            JOIN sys_role_permission role_permission
              ON role_permission.role_id = user_role.role_id
            JOIN sys_permission permission
              ON permission.permission_id = role_permission.permission_id
            JOIN sys_scope_binding scope_binding
              ON (
                (
                  scope_binding.subject_type = 'USER'
                  AND scope_binding.subject_id = user_account.user_id
                )
                OR (
                  scope_binding.subject_type = 'ROLE'
                  AND scope_binding.subject_id = user_role.role_id
                )
              )
            WHERE user_account.external_subject = ?
              AND user_account.status = 'ACTIVE'
              AND permission.permission_code = ?
              AND (
                scope_binding.scope_type = 'STATION'
                  AND scope_binding.scope_id = capture.station_id
                OR scope_binding.scope_type = 'LINE'
                  AND scope_binding.scope_id = station.line_id
                OR scope_binding.scope_type = 'ORGANIZATION'
                  AND scope_binding.scope_id = line.organization_id
              )
        )
        """;

    private final JdbcTemplate jdbc;

    public JdbcReviewRepository(JdbcTemplate jdbc) {
        this.jdbc = java.util.Objects.requireNonNull(jdbc);
    }

    @Override
    public void requeueExpired(Instant now) {
        jdbc.update(
            """
            UPDATE review_task
            SET status = COALESCE(claimed_from_status, 'PENDING'),
                claimed_by = NULL,
                lease_expires_at = NULL,
                claimed_from_status = NULL,
                updated_at = ?,
                record_version = record_version + 1
            WHERE status = 'CLAIMED'
              AND lease_expires_at <= ?
            """,
            Timestamp.from(now),
            Timestamp.from(now)
        );
    }

    @Override
    public Map<String, Object> list(
            String actorId,
            String cursor,
            int pageSize,
            String status) {
        Cursor boundary = cursor == null ? null : decodeCursor(cursor);
        StringBuilder sql = new StringBuilder("""
            SELECT task.*,
                   claimed_user.external_subject AS claimed_external_subject
            FROM review_task task
            JOIN capture_event capture
              ON capture.capture_id = task.capture_id
            JOIN station station
              ON station.station_id = capture.station_id
            JOIN production_line line
              ON line.line_id = station.line_id
            LEFT JOIN sys_user claimed_user
              ON claimed_user.user_id = task.claimed_by
            WHERE
            """);
        sql.append(AUTHORIZED_SCOPE);
        List<Object> arguments = new ArrayList<>();
        arguments.add(actorId);
        arguments.add("review:read");
        if (status != null) {
            sql.append(" AND task.status = ?");
            arguments.add(status);
        }
        if (boundary != null) {
            sql.append(
                """
                 AND (
                    task.priority,
                    task.created_at,
                    task.review_task_id
                 ) > (?, ?, ?)
                """
            );
            arguments.add(boundary.priority());
            arguments.add(Timestamp.from(boundary.createdAt()));
            arguments.add(boundary.reviewTaskId());
        }
        sql.append(
            """
             ORDER BY task.priority,
                      task.created_at,
                      task.review_task_id
             LIMIT ?
            """
        );
        arguments.add(pageSize + 1);
        List<ReviewTaskState> rows = jdbc.query(
            sql.toString(),
            JdbcReviewRepository::mapTask,
            arguments.toArray()
        );
        boolean hasMore = rows.size() > pageSize;
        if (hasMore) {
            rows = new ArrayList<>(rows.subList(0, pageSize));
        }
        List<Map<String, Object>> items = rows.stream()
            .map(ReviewTaskState::contractView)
            .toList();
        String nextCursor = hasMore && !rows.isEmpty()
            ? encodeCursor(rows.get(rows.size() - 1))
            : null;
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("items", items);
        response.put("next_cursor", nextCursor);
        response.put("has_more", hasMore);
        return Collections.unmodifiableMap(response);
    }

    @Override
    public ReviewTaskState requireAuthorized(
            String actorId,
            UUID reviewTaskId,
            String permission,
            boolean forUpdate) {
        String sql = """
            SELECT task.*,
                   claimed_user.external_subject AS claimed_external_subject
            FROM review_task task
            JOIN capture_event capture
              ON capture.capture_id = task.capture_id
            JOIN station station
              ON station.station_id = capture.station_id
            JOIN production_line line
              ON line.line_id = station.line_id
            LEFT JOIN sys_user claimed_user
              ON claimed_user.user_id = task.claimed_by
            WHERE task.review_task_id = ?
              AND
            """ + AUTHORIZED_SCOPE + (forUpdate ? " FOR UPDATE OF task" : "");
        return jdbc.query(
            sql,
            JdbcReviewRepository::mapTask,
            reviewTaskId,
            actorId,
            permission
        ).stream().findFirst().orElseThrow(() ->
            new ReviewNotFound("复核任务不存在或不在当前权限范围")
        );
    }

    @Override
    public boolean hasPermission(String actorId, String permission) {
        Boolean allowed = jdbc.queryForObject(
            """
            SELECT EXISTS (
                SELECT 1
                FROM sys_user user_account
                JOIN sys_user_role user_role
                  ON user_role.user_id = user_account.user_id
                JOIN sys_role_permission role_permission
                  ON role_permission.role_id = user_role.role_id
                JOIN sys_permission permission_record
                  ON permission_record.permission_id =
                     role_permission.permission_id
                WHERE user_account.external_subject = ?
                  AND user_account.status = 'ACTIVE'
                  AND permission_record.permission_code = ?
            )
            """,
            Boolean.class,
            actorId,
            permission
        );
        return Boolean.TRUE.equals(allowed);
    }

    @Override
    public boolean claim(
            UUID reviewTaskId,
            String actorId,
            long expectedVersion,
            Instant leaseExpiresAt,
            String claimedFromStatus) {
        return jdbc.update(
            """
            UPDATE review_task
            SET status = 'CLAIMED',
                claimed_by = (
                    SELECT user_id
                    FROM sys_user
                    WHERE external_subject = ?
                      AND status = 'ACTIVE'
                ),
                lease_expires_at = ?,
                claimed_from_status = ?,
                updated_at = now(),
                record_version = record_version + 1
            WHERE review_task_id = ?
              AND status = ?
              AND record_version = ?
            """,
            actorId,
            Timestamp.from(leaseExpiresAt),
            claimedFromStatus,
            reviewTaskId,
            claimedFromStatus,
            expectedVersion
        ) == 1;
    }

    @Override
    public boolean release(
            UUID reviewTaskId,
            String actorId,
            long expectedVersion,
            String restoredStatus) {
        return jdbc.update(
            """
            UPDATE review_task
            SET status = ?,
                claimed_by = NULL,
                lease_expires_at = NULL,
                claimed_from_status = NULL,
                updated_at = now(),
                record_version = record_version + 1
            WHERE review_task_id = ?
              AND status = 'CLAIMED'
              AND claimed_by = (
                    SELECT user_id
                    FROM sys_user
                    WHERE external_subject = ?
              )
              AND record_version = ?
            """,
            restoredStatus,
            reviewTaskId,
            actorId,
            expectedVersion
        ) == 1;
    }

    @Override
    public boolean changePriority(
            UUID reviewTaskId,
            long expectedVersion,
            int priority) {
        return jdbc.update(
            """
            UPDATE review_task
            SET priority = ?,
                updated_at = now(),
                record_version = record_version + 1
            WHERE review_task_id = ?
              AND status NOT IN ('RESOLVED', 'CANCELLED')
              AND record_version = ?
            """,
            priority,
            reviewTaskId,
            expectedVersion
        ) == 1;
    }

    @Override
    public List<ReviewRecordState> records(UUID reviewTaskId) {
        return jdbc.query(
            """
            SELECT record.review_record_id,
                   user_account.external_subject AS reviewer_id,
                   record.decision,
                   record.reason_code,
                   record.review_round,
                   record.independent_review_group,
                   record.supersedes_id,
                   record.adjudication,
                   record.submitted_at
            FROM review_record record
            JOIN sys_user user_account
              ON user_account.user_id = record.reviewer_id
            WHERE record.review_task_id = ?
            ORDER BY record.review_round,
                     record.submitted_at,
                     record.review_record_id
            """,
            (row, index) -> new ReviewRecordState(
                row.getObject("review_record_id", UUID.class),
                row.getString("reviewer_id"),
                row.getString("decision"),
                row.getString("reason_code"),
                row.getInt("review_round"),
                row.getObject("independent_review_group", UUID.class),
                row.getObject("supersedes_id", UUID.class),
                row.getBoolean("adjudication"),
                row.getTimestamp("submitted_at").toInstant()
            ),
            reviewTaskId
        );
    }

    @Override
    public void insertRecord(
            UUID reviewRecordId,
            ReviewTaskState task,
            String actorId,
            ReviewSubmission submission,
            int reviewRound,
            UUID independentReviewGroup,
            UUID supersedesId,
            boolean adjudication,
            String submissionSha256,
            Instant submittedAt) {
        int inserted = jdbc.update(
            """
            INSERT INTO review_record(
                review_record_id,
                review_task_id,
                reviewer_id,
                decision,
                reason_code,
                comment,
                annotation_image_id,
                defect_type_codes,
                review_round,
                independent_review_group,
                supersedes_id,
                submitted_at,
                client_submitted_at,
                submission_sha256,
                adjudication
            ) VALUES (
                ?,
                ?,
                (
                    SELECT user_id
                    FROM sys_user
                    WHERE external_subject = ?
                      AND status = 'ACTIVE'
                ),
                ?,
                ?,
                ?,
                ?,
                CAST(? AS jsonb),
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
            """,
            reviewRecordId,
            task.reviewTaskId(),
            actorId,
            submission.decision(),
            submission.reasonCode(),
            submission.comment(),
            submission.annotationImageId(),
            CanonicalJson.encode(submission.defectTypeCodes()),
            reviewRound,
            independentReviewGroup,
            supersedesId,
            Timestamp.from(submittedAt),
            Timestamp.from(submission.clientSubmittedAt()),
            submissionSha256,
            adjudication
        );
        if (inserted != 1) {
            throw new DomainViolation("不可变复核记录写入失败");
        }
    }

    @Override
    public boolean completeClaim(
            UUID reviewTaskId,
            String actorId,
            long expectedVersion,
            String nextStatus) {
        return jdbc.update(
            """
            UPDATE review_task
            SET status = ?,
                claimed_by = NULL,
                lease_expires_at = NULL,
                claimed_from_status = NULL,
                updated_at = now(),
                record_version = record_version + 1
            WHERE review_task_id = ?
              AND status = 'CLAIMED'
              AND claimed_by = (
                    SELECT user_id
                    FROM sys_user
                    WHERE external_subject = ?
              )
              AND lease_expires_at > now()
              AND record_version = ?
            """,
            nextStatus,
            reviewTaskId,
            actorId,
            expectedVersion
        ) == 1;
    }

    @Override
    public void appendDisposition(
            UUID dispositionId,
            ReviewTaskState task,
            UUID reviewRecordId,
            String actorId,
            String decision,
            String reasonCode,
            Instant createdAt) {
        int inserted = jdbc.update(
            """
            INSERT INTO disposition_record(
                disposition_id,
                capture_id,
                source,
                disposition,
                review_record_id,
                reason_code,
                actor_id,
                supersedes_id,
                created_at
            ) VALUES (
                ?,
                ?,
                'REVIEW',
                ?,
                ?,
                ?,
                (
                    SELECT user_id
                    FROM sys_user
                    WHERE external_subject = ?
                      AND status = 'ACTIVE'
                ),
                (
                    SELECT current_disposition_id
                    FROM capture_event
                    WHERE capture_id = ?
                ),
                ?
            )
            """,
            dispositionId,
            task.captureId(),
            decision,
            reviewRecordId,
            reasonCode,
            actorId,
            task.captureId(),
            Timestamp.from(createdAt)
        );
        if (inserted != 1) {
            throw new DomainViolation("人工处置记录写入失败");
        }
        if (jdbc.update(
                """
                UPDATE capture_event
                SET status = 'FINALIZED',
                    current_disposition = ?,
                    current_disposition_id = ?,
                    updated_at = now(),
                    record_version = record_version + 1
                WHERE capture_id = ?
                """,
                decision,
                dispositionId,
                task.captureId()
            ) != 1) {
            throw new DomainViolation("采集当前处置投影更新失败");
        }
    }

    @Override
    public UUID openRevision(
            UUID newTaskId,
            ReviewTaskState resolvedTask,
            UUID supersededReviewRecordId,
            int priority,
            Instant createdAt) {
        int inserted = jdbc.update(
            """
            INSERT INTO review_task(
                review_task_id,
                capture_id,
                priority,
                status,
                pool_scope,
                trigger_reasons,
                requires_second_review,
                revision_of_task_id,
                supersedes_review_record_id,
                created_at,
                updated_at
            )
            SELECT ?,
                   capture_id,
                   ?,
                   'PENDING',
                   pool_scope,
                   jsonb_build_array('CORRECTION_REVISION'),
                   requires_second_review,
                   review_task_id,
                   ?,
                   ?,
                   ?
            FROM review_task
            WHERE review_task_id = ?
              AND status = 'RESOLVED'
            """,
            newTaskId,
            priority,
            supersededReviewRecordId,
            Timestamp.from(createdAt),
            Timestamp.from(createdAt),
            resolvedTask.reviewTaskId()
        );
        if (inserted != 1) {
            throw new ReviewConflict("纠错修订创建发生并发冲突");
        }
        return newTaskId;
    }

    @Override
    public void appendTrainingDecision(
            UUID decisionId,
            UUID reviewRecordId,
            String actorId,
            String decision,
            String reason,
            Instant createdAt) {
        int inserted = jdbc.update(
            """
            INSERT INTO review_training_decision(
                training_decision_id,
                review_record_id,
                decision,
                decided_by,
                reason,
                created_at
            ) VALUES (
                ?,
                ?,
                ?,
                (
                    SELECT user_id
                    FROM sys_user
                    WHERE external_subject = ?
                      AND status = 'ACTIVE'
                ),
                ?,
                ?
            )
            """,
            decisionId,
            reviewRecordId,
            decision,
            actorId,
            reason,
            Timestamp.from(createdAt)
        );
        if (inserted != 1) {
            throw new DomainViolation("训练候选质量决定写入失败");
        }
    }

    private static ReviewTaskState mapTask(ResultSet row, int index)
            throws SQLException {
        Timestamp lease = row.getTimestamp("lease_expires_at");
        String claimedFrom = row.getString("claimed_from_status");
        return new ReviewTaskState(
            row.getObject("review_task_id", UUID.class),
            row.getObject("capture_id", UUID.class),
            row.getInt("priority"),
            ReviewStatus.valueOf(row.getString("status")),
            claimedBy(row),
            lease == null ? null : lease.toInstant(),
            claimedFrom == null ? null : ReviewStatus.valueOf(claimedFrom),
            row.getBoolean("requires_second_review"),
            row.getLong("record_version"),
            row.getObject("revision_of_task_id", UUID.class),
            row.getObject("supersedes_review_record_id", UUID.class),
            row.getTimestamp("created_at").toInstant()
        );
    }

    private static String claimedBy(ResultSet row) throws SQLException {
        return row.getString("claimed_external_subject");
    }

    private static String encodeCursor(ReviewTaskState task) {
        String value = task.priority()
            + "\n"
            + task.createdAt()
            + "\n"
            + task.reviewTaskId();
        return Base64.getUrlEncoder().withoutPadding().encodeToString(
            value.getBytes(StandardCharsets.UTF_8)
        );
    }

    private static Cursor decodeCursor(String cursor) {
        try {
            String decoded = new String(
                Base64.getUrlDecoder().decode(cursor),
                StandardCharsets.UTF_8
            );
            String[] parts = decoded.split("\\n", -1);
            if (parts.length != 3) {
                throw new IllegalArgumentException("cursor parts");
            }
            return new Cursor(
                Integer.parseInt(parts[0]),
                Instant.parse(parts[1]),
                UUID.fromString(parts[2])
            );
        } catch (RuntimeException invalid) {
            throw new DomainViolation("复核任务游标不合法", invalid);
        }
    }

    private record Cursor(
        int priority,
        Instant createdAt,
        UUID reviewTaskId) {
    }
}
