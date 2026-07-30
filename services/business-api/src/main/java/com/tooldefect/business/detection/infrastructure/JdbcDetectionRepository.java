package com.tooldefect.business.detection.infrastructure;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.detection.application.DetectionFailureSubmission;
import com.tooldefect.business.detection.application.DetectionRepository;
import com.tooldefect.business.detection.application.DetectionResultSubmission;
import com.tooldefect.business.detection.domain.DispositionDecision;
import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.domain.IdempotencyConflict;

@Repository
public class JdbcDetectionRepository implements DetectionRepository {
    private final JdbcTemplate jdbc;

    public JdbcDetectionRepository(JdbcTemplate jdbc) {
        this.jdbc = java.util.Objects.requireNonNull(jdbc);
    }

    @Override
    public AttemptStart startAttempt(
            UUID detectionTaskId,
            UUID attemptId,
            String sourceMessageId,
            String workerId,
            String runtimeVersion,
            String modelSha256,
            String traceId,
            Instant startedAt) {
        var replay = jdbc.query(
            """
            SELECT attempt_id, detection_task_id, attempt_no, model_sha256
            FROM detection_attempt
            WHERE source_message_id = ?
            """,
            (row, rowNumber) -> new ExistingAttempt(
                row.getObject("attempt_id", UUID.class),
                row.getObject("detection_task_id", UUID.class),
                row.getInt("attempt_no"),
                row.getString("model_sha256").trim()
            ),
            sourceMessageId
        ).stream().findFirst();
        if (replay.isPresent()) {
            if (!replay.get().detectionTaskId().equals(detectionTaskId)
                    || !replay.get().modelSha256().equals(modelSha256)) {
                throw new IdempotencyConflict(
                    "队列消息已经绑定不同检测任务或模型"
                );
            }
            return new AttemptStart(
                replay.get().attemptId(),
                replay.get().attemptNumber(),
                true
            );
        }

        TaskForAttempt task = jdbc.query(
            """
            SELECT t.status,
                   t.attempt_count,
                   t.next_retry_at,
                   mv.artifact_sha256 AS model_sha256
            FROM detection_task t
            JOIN pipeline_version p ON p.pipeline_id = t.pipeline_id
            JOIN model_version mv ON mv.model_version_id = p.model_version_id
            WHERE t.detection_task_id = ?
            FOR UPDATE OF t
            """,
            (row, rowNumber) -> new TaskForAttempt(
                row.getString("status"),
                row.getInt("attempt_count"),
                nullableInstant(row, "next_retry_at"),
                row.getString("model_sha256").trim()
            ),
            detectionTaskId
        ).stream().findFirst().orElseThrow(() ->
            new DomainViolation("检测任务不存在")
        );
        if (!task.modelSha256().equals(modelSha256)) {
            throw new DomainViolation("工作进程模型哈希与锁定任务不一致");
        }
        boolean dueRetry = "RETRY_WAIT".equals(task.status())
            && task.nextRetryAt() != null
            && !task.nextRetryAt().isAfter(startedAt);
        if (!"QUEUED".equals(task.status()) && !dueRetry) {
            throw new DomainViolation("检测任务当前不能开始新的执行尝试");
        }
        int attemptNumber = task.attemptCount() + 1;
        jdbc.update(
            """
            INSERT INTO detection_attempt(
                attempt_id,
                detection_task_id,
                attempt_no,
                worker_id,
                runtime_version,
                model_sha256,
                trace_id,
                status,
                started_at,
                source_message_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?, ?)
            """,
            attemptId,
            detectionTaskId,
            attemptNumber,
            workerId,
            runtimeVersion,
            modelSha256,
            traceId,
            Timestamp.from(startedAt),
            sourceMessageId
        );
        requireOne(
            jdbc.update(
                """
                UPDATE detection_task
                SET status = 'RUNNING',
                    attempt_count = ?,
                    next_retry_at = NULL,
                    started_at = COALESCE(started_at, ?),
                    updated_at = now(),
                    record_version = record_version + 1
                WHERE detection_task_id = ?
                """,
                attemptNumber,
                Timestamp.from(startedAt),
                detectionTaskId
            ),
            "检测任务开始失败"
        );
        int captureUpdated = jdbc.update(
            """
            UPDATE capture_event
            SET status = 'PROCESSING',
                updated_at = now(),
                record_version = record_version + 1
            WHERE capture_id = (
                SELECT capture_id
                FROM detection_task
                WHERE detection_task_id = ?
            )
              AND status = 'SUBMITTED'
            """,
            detectionTaskId
        );
        if (captureUpdated == 0) {
            String captureStatus = jdbc.queryForObject(
                """
                SELECT c.status
                FROM capture_event c
                JOIN detection_task t ON t.capture_id = c.capture_id
                WHERE t.detection_task_id = ?
                """,
                String.class,
                detectionTaskId
            );
            if (!"PROCESSING".equals(captureStatus)) {
                throw new DomainViolation(
                    "中央采集状态不能推进到 PROCESSING"
                );
            }
        }
        return new AttemptStart(attemptId, attemptNumber, false);
    }

    @Override
    public AttemptContext lockAttempt(UUID attemptId) {
        return jdbc.query(
            """
            SELECT a.attempt_id,
                   a.detection_task_id,
                   t.capture_id,
                   c.station_id,
                   a.attempt_no,
                   a.status AS attempt_status,
                   t.status AS task_status,
                   a.callback_sha256,
                   r.result_sha256 AS accepted_result_sha256,
                   mv.version AS expected_model_version,
                   mv.artifact_sha256 AS expected_model_sha256,
                   c.quality_status,
                   COALESCE((c.attributes->>'forced_review')::boolean, false)
                       AS forced_review,
                   COALESCE((c.attributes->>'sampled_review')::boolean, false)
                       AS sampled_review
            FROM detection_attempt a
            JOIN detection_task t
                ON t.detection_task_id = a.detection_task_id
            JOIN capture_event c ON c.capture_id = t.capture_id
            JOIN pipeline_version p ON p.pipeline_id = t.pipeline_id
            JOIN model_version mv ON mv.model_version_id = p.model_version_id
            LEFT JOIN detection_result r
                ON r.accepted_attempt_id = a.attempt_id
            WHERE a.attempt_id = ?
            FOR UPDATE OF a, t, c
            """,
            JdbcDetectionRepository::mapAttemptContext,
            attemptId
        ).stream().findFirst().orElseThrow(() ->
            new DomainViolation("执行尝试不存在")
        );
    }

    @Override
    public void acceptResult(
            AttemptContext context,
            UUID detectionResultId,
            DetectionResultSubmission result,
            String resultSha256,
            DispositionDecision decision,
            UUID dispositionId,
            UUID reviewTaskId,
            List<UUID> regionIds,
            Instant acceptedAt) {
        requireOne(
            jdbc.update(
                """
                UPDATE detection_attempt
                SET status = 'SUCCEEDED',
                    finished_at = ?,
                    timings = CAST(? AS jsonb),
                    callback_sha256 = ?
                WHERE attempt_id = ?
                  AND status = 'RUNNING'
                """,
                Timestamp.from(acceptedAt),
                CanonicalJson.encode(result.timings()),
                resultSha256,
                context.attemptId()
            ),
            "执行尝试结果发生并发冲突"
        );
        requireOne(
            jdbc.update(
                """
                INSERT INTO detection_result(
                    detection_result_id,
                    detection_task_id,
                    accepted_attempt_id,
                    schema_version,
                    algorithm_outcome,
                    confidence,
                    qualified_probability,
                    unqualified_probability,
                    preprocess_quality,
                    region_count,
                    warnings,
                    standard_result,
                    result_sha256
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS jsonb),
                        CAST(? AS jsonb), ?)
                """,
                detectionResultId,
                context.detectionTaskId(),
                context.attemptId(),
                result.schemaVersion(),
                result.algorithmOutcome(),
                result.confidence().isPresent()
                    ? result.confidence().getAsDouble()
                    : null,
                result.qualifiedProbability(),
                result.unqualifiedProbability(),
                result.preprocessQuality(),
                result.regions().size(),
                CanonicalJson.encode(result.warnings()),
                CanonicalJson.encode(result.raw()),
                resultSha256
            ),
            "标准检测结果插入失败"
        );
        if (regionIds.size() != result.regions().size()) {
            throw new IllegalArgumentException("区域标识数量不一致");
        }
        for (int index = 0; index < result.regions().size(); index++) {
            insertRegion(
                regionIds.get(index),
                detectionResultId,
                result.regions().get(index)
            );
        }
        requireOne(
            jdbc.update(
                """
                UPDATE detection_task
                SET status = 'SUCCEEDED',
                    finished_at = ?,
                    last_error_code = NULL,
                    updated_at = now(),
                    record_version = record_version + 1
                WHERE detection_task_id = ?
                  AND status = 'RUNNING'
                """,
                Timestamp.from(acceptedAt),
                context.detectionTaskId()
            ),
            "检测任务结果接受发生并发冲突"
        );
        appendDisposition(
            context,
            decision,
            dispositionId,
            acceptedAt
        );
        projectDisposition(
            context,
            decision,
            dispositionId,
            acceptedAt
        );
        if (decision.requiresReview()) {
            insertReviewTask(
                reviewTaskId,
                context,
                decision.reasonCode(),
                acceptedAt
            );
        }
        insertAudit(
            "DETECTION_RESULT_ACCEPTED",
            "detection_task",
            context.detectionTaskId(),
            resultSha256,
            acceptedAt,
            null
        );
    }

    @Override
    public void acceptFailure(
            AttemptContext context,
            DetectionFailureSubmission failure,
            String failureSha256,
            int maximumAttempts,
            Instant retryAt,
            DispositionDecision terminalDecision,
            UUID dispositionId,
            UUID reviewTaskId,
            Instant acceptedAt) {
        requireOne(
            jdbc.update(
                """
                UPDATE detection_attempt
                SET status = 'FAILED',
                    finished_at = ?,
                    error_code = ?,
                    error_message = ?,
                    callback_sha256 = ?
                WHERE attempt_id = ?
                  AND status = 'RUNNING'
                """,
                Timestamp.from(acceptedAt),
                failure.errorCode(),
                truncate(failure.message(), 512),
                failureSha256,
                context.attemptId()
            ),
            "执行失败回调发生并发冲突"
        );
        boolean retry = terminalDecision == null
            && failure.retryable()
            && context.attemptNumber() < maximumAttempts;
        if (retry) {
            requireOne(
                jdbc.update(
                    """
                    UPDATE detection_task
                    SET status = 'RETRY_WAIT',
                        next_retry_at = ?,
                        last_error_code = ?,
                        updated_at = now(),
                        record_version = record_version + 1
                    WHERE detection_task_id = ?
                      AND status = 'RUNNING'
                    """,
                    Timestamp.from(retryAt),
                    failure.errorCode(),
                    context.detectionTaskId()
                ),
                "检测任务重试状态推进失败"
            );
        } else {
            requireOne(
                jdbc.update(
                    """
                    UPDATE detection_task
                    SET status = 'DEAD',
                        finished_at = ?,
                        next_retry_at = NULL,
                        last_error_code = ?,
                        updated_at = now(),
                        record_version = record_version + 1
                    WHERE detection_task_id = ?
                      AND status = 'RUNNING'
                    """,
                    Timestamp.from(acceptedAt),
                    failure.errorCode(),
                    context.detectionTaskId()
                ),
                "检测任务终止状态推进失败"
            );
            appendDisposition(
                context,
                terminalDecision,
                dispositionId,
                acceptedAt
            );
            projectDisposition(
                context,
                terminalDecision,
                dispositionId,
                acceptedAt
            );
            insertReviewTask(
                reviewTaskId,
                context,
                terminalDecision.reasonCode(),
                acceptedAt
            );
        }
        insertAudit(
            "DETECTION_ATTEMPT_FAILED",
            "detection_attempt",
            context.attemptId(),
            failureSha256,
            acceptedAt,
            failure.errorCode()
        );
    }

    private void insertRegion(
            UUID regionId,
            UUID detectionResultId,
            DetectionResultSubmission.Region region) {
        jdbc.update(
            """
            INSERT INTO defect_region(
                region_id,
                detection_result_id,
                region_no,
                coordinate_space,
                geometry_type,
                geometry,
                peak_score,
                mean_score,
                attributes
            )
            VALUES (?, ?, ?, ?, ?, CAST(? AS jsonb), ?, ?, CAST(? AS jsonb))
            """,
            regionId,
            detectionResultId,
            region.regionNumber(),
            region.coordinateSpace(),
            region.geometryType(),
            CanonicalJson.encode(region.geometry()),
            score(region.scores(), "peak"),
            score(region.scores(), "mean"),
            CanonicalJson.encode(region.attributes())
        );
    }

    private void appendDisposition(
            AttemptContext context,
            DispositionDecision decision,
            UUID dispositionId,
            Instant acceptedAt) {
        Map<String, Object> evidence = Map.of(
            "policy", decision.policySnapshot(),
            "input_summary", decision.inputSummary()
        );
        jdbc.update(
            """
            INSERT INTO disposition_record(
                disposition_id,
                capture_id,
                source,
                disposition,
                policy_version,
                reason_code,
                policy_snapshot,
                input_summary_sha256,
                created_at
            )
            VALUES (?, ?, 'AUTO', ?, ?, ?, CAST(? AS jsonb), ?, ?)
            """,
            dispositionId,
            context.captureId(),
            decision.disposition().name(),
            decision.policyVersion(),
            decision.reasonCode(),
            CanonicalJson.encode(evidence),
            CanonicalJson.sha256(decision.inputSummary()),
            Timestamp.from(acceptedAt)
        );
    }

    private void projectDisposition(
            AttemptContext context,
            DispositionDecision decision,
            UUID dispositionId,
            Instant acceptedAt) {
        String status = decision.requiresReview()
            ? "REVIEW_PENDING"
            : "FINALIZED";
        requireOne(
            jdbc.update(
                """
                UPDATE capture_event
                SET status = ?,
                    current_disposition = ?,
                    current_disposition_id = ?,
                    updated_at = ?,
                    record_version = record_version + 1
                WHERE capture_id = ?
                  AND status = 'PROCESSING'
                """,
                status,
                decision.disposition().name(),
                dispositionId,
                Timestamp.from(acceptedAt),
                context.captureId()
            ),
            "采集处置投影发生并发冲突"
        );
    }

    private void insertReviewTask(
            UUID reviewTaskId,
            AttemptContext context,
            String reason,
            Instant acceptedAt) {
        jdbc.update(
            """
            INSERT INTO review_task(
                review_task_id,
                capture_id,
                priority,
                status,
                pool_scope,
                trigger_reasons,
                created_at,
                updated_at
            )
            VALUES (?, ?, 10, 'PENDING', CAST(? AS jsonb),
                    CAST(? AS jsonb), ?, ?)
            """,
            reviewTaskId,
            context.captureId(),
            CanonicalJson.encode(Map.of(
                "station_id", context.stationId().toString()
            )),
            CanonicalJson.encode(List.of(reason)),
            Timestamp.from(acceptedAt),
            Timestamp.from(acceptedAt)
        );
    }

    private void insertAudit(
            String action,
            String resourceType,
            UUID resourceId,
            String digest,
            Instant occurredAt,
            String errorCode) {
        UUID auditId = resourceId;
        jdbc.update(
            """
            INSERT INTO audit_log(
                audit_id,
                occurred_at,
                actor_type,
                actor_id,
                action,
                resource_type,
                resource_id,
                after_digest,
                request_id,
                trace_id,
                result,
                error_code
            )
            VALUES (?, ?, 'SERVICE', 'inference-service', ?, ?, ?, ?, ?, ?,
                    ?, ?)
            """,
            auditId,
            Timestamp.from(occurredAt),
            action,
            resourceType,
            resourceId.toString(),
            digest,
            auditId.toString(),
            digest.substring(0, 32),
            errorCode == null ? "SUCCEEDED" : "FAILED",
            errorCode
        );
    }

    private static AttemptContext mapAttemptContext(
            ResultSet row,
            int rowNumber) throws SQLException {
        return new AttemptContext(
            row.getObject("attempt_id", UUID.class),
            row.getObject("detection_task_id", UUID.class),
            row.getObject("capture_id", UUID.class),
            row.getObject("station_id", UUID.class),
            row.getInt("attempt_no"),
            row.getString("attempt_status"),
            row.getString("task_status"),
            trimNullable(row.getString("callback_sha256")),
            trimNullable(row.getString("accepted_result_sha256")),
            row.getString("expected_model_version"),
            row.getString("expected_model_sha256").trim(),
            row.getString("quality_status"),
            row.getBoolean("forced_review"),
            row.getBoolean("sampled_review")
        );
    }

    private static Double score(Map<String, Object> scores, String name) {
        Object value = scores.get(name);
        return value instanceof Number number ? number.doubleValue() : null;
    }

    private static void requireOne(int count, String message) {
        if (count != 1) {
            throw new DomainViolation(message);
        }
    }

    private static String truncate(String value, int maximum) {
        return value.length() <= maximum ? value : value.substring(0, maximum);
    }

    private static String trimNullable(String value) {
        return value == null ? null : value.trim();
    }

    private static Instant nullableInstant(ResultSet row, String column)
            throws SQLException {
        Timestamp value = row.getTimestamp(column);
        return value == null ? null : value.toInstant();
    }

    private record ExistingAttempt(
        UUID attemptId,
        UUID detectionTaskId,
        int attemptNumber,
        String modelSha256
    ) {}

    private record TaskForAttempt(
        String status,
        int attemptCount,
        Instant nextRetryAt,
        String modelSha256
    ) {}
}
