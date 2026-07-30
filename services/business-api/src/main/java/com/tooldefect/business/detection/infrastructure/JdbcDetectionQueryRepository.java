package com.tooldefect.business.detection.infrastructure;

import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.detection.application.DetectionQueryRepository;
import com.tooldefect.business.detection.domain.DetectionNotFound;
import com.tooldefect.business.shared.api.ContractValues;

@Repository
public class JdbcDetectionQueryRepository
        implements DetectionQueryRepository {
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
                  AND scope_binding.scope_id = c.station_id
                OR scope_binding.scope_type = 'LINE'
                  AND scope_binding.scope_id = s.line_id
                OR scope_binding.scope_type = 'ORGANIZATION'
                  AND scope_binding.scope_id = l.organization_id
              )
        )
        """;

    private final JdbcTemplate jdbc;

    public JdbcDetectionQueryRepository(JdbcTemplate jdbc) {
        this.jdbc = java.util.Objects.requireNonNull(jdbc);
    }

    @Override
    public Map<String, Object> list(
            String actorId,
            String cursor,
            int pageSize,
            String businessDisposition,
            String algorithmOutcome,
            String modelVersion) {
        Cursor boundary = cursor == null ? null : decodeCursor(cursor);
        StringBuilder sql = new StringBuilder("""
            SELECT t.detection_task_id,
                   t.status AS task_status,
                   t.queued_at,
                   r.algorithm_outcome,
                   r.confidence,
                   mv.version AS model_version
            FROM detection_task t
            JOIN capture_event c ON c.capture_id = t.capture_id
            JOIN station s ON s.station_id = c.station_id
            JOIN production_line l ON l.line_id = s.line_id
            JOIN pipeline_version p ON p.pipeline_id = t.pipeline_id
            JOIN model_version mv ON mv.model_version_id = p.model_version_id
            LEFT JOIN detection_result r
              ON r.detection_task_id = t.detection_task_id
            WHERE
            """);
        sql.append(AUTHORIZED_SCOPE);
        List<Object> arguments = new ArrayList<>();
        arguments.add(actorId);
        arguments.add("detection:read");
        if (businessDisposition != null) {
            sql.append(" AND c.current_disposition = ?");
            arguments.add(businessDisposition);
        }
        if (algorithmOutcome != null) {
            sql.append(" AND r.algorithm_outcome = ?");
            arguments.add(algorithmOutcome);
        }
        if (modelVersion != null) {
            sql.append(" AND mv.version = ?");
            arguments.add(modelVersion);
        }
        if (boundary != null) {
            sql.append(
                " AND (t.queued_at, t.detection_task_id) < (?, ?)"
            );
            arguments.add(Timestamp.from(boundary.queuedAt()));
            arguments.add(boundary.detectionTaskId());
        }
        sql.append(
            " ORDER BY t.queued_at DESC, t.detection_task_id DESC LIMIT ?"
        );
        arguments.add(pageSize + 1);
        List<ListRow> rows = jdbc.query(
            sql.toString(),
            JdbcDetectionQueryRepository::mapListRow,
            arguments.toArray()
        );
        boolean hasMore = rows.size() > pageSize;
        if (hasMore) {
            rows = new ArrayList<>(rows.subList(0, pageSize));
        }
        List<Map<String, Object>> items = rows.stream()
            .map(ListRow::summary)
            .toList();
        String nextCursor = hasMore && !rows.isEmpty()
            ? encodeCursor(rows.get(rows.size() - 1))
            : null;
        return immutableMap(
            "items", items,
            "next_cursor", nextCursor,
            "has_more", hasMore
        );
    }

    @Override
    public Map<String, Object> detail(
            String actorId,
            UUID detectionTaskId) {
        return detail(actorId, detectionTaskId, "detection:read");
    }

    @Override
    public Map<String, Object> detailByCapture(
            String actorId,
            UUID captureId,
            String permission) {
        UUID detectionTaskId = jdbc.query(
            """
            SELECT t.detection_task_id
            FROM detection_task t
            JOIN capture_event c ON c.capture_id = t.capture_id
            JOIN station s ON s.station_id = c.station_id
            JOIN production_line l ON l.line_id = s.line_id
            WHERE t.capture_id = ?
              AND
            """
                + AUTHORIZED_SCOPE
                + """
                 ORDER BY t.queued_at DESC, t.detection_task_id DESC
                 LIMIT 1
                """,
            (row, index) ->
                row.getObject("detection_task_id", UUID.class),
            captureId,
            actorId,
            permission
        ).stream().findFirst().orElseThrow(() ->
            new DetectionNotFound("复核证据不存在或不在当前数据范围")
        );
        return detail(actorId, detectionTaskId, permission);
    }

    private Map<String, Object> detail(
            String actorId,
            UUID detectionTaskId,
            String permission) {
        MainRow main = jdbc.query(
            """
            SELECT t.detection_task_id,
                   t.status AS task_status,
                   t.capture_id,
                   t.pipeline_id,
                   c.status AS capture_status,
                   c.current_disposition,
                   r.algorithm_outcome,
                   r.confidence,
                   mv.version AS model_version,
                   p.version AS pipeline_version,
                   p.preprocessor_version,
                   p.algorithm_version,
                   latest_disposition.policy_version,
                   latest_review.status AS review_status
            FROM detection_task t
            JOIN capture_event c ON c.capture_id = t.capture_id
            JOIN station s ON s.station_id = c.station_id
            JOIN production_line l ON l.line_id = s.line_id
            JOIN pipeline_version p ON p.pipeline_id = t.pipeline_id
            JOIN model_version mv ON mv.model_version_id = p.model_version_id
            LEFT JOIN detection_result r
              ON r.detection_task_id = t.detection_task_id
            LEFT JOIN disposition_record latest_disposition
              ON latest_disposition.disposition_id = c.current_disposition_id
            LEFT JOIN LATERAL (
                SELECT status
                FROM review_task
                WHERE capture_id = c.capture_id
                ORDER BY created_at DESC
                LIMIT 1
            ) latest_review ON true
            WHERE t.detection_task_id = ?
              AND
            """
                + AUTHORIZED_SCOPE,
            JdbcDetectionQueryRepository::mapMainRow,
            detectionTaskId,
            actorId,
            permission
        ).stream().findFirst().orElseThrow(() ->
            new DetectionNotFound("检测任务不存在或不在当前数据范围")
        );
        Map<String, Object> summary = summary(main);
        Map<String, Object> capture = immutableMap(
            "capture_id", main.captureId().toString(),
            "capture_status", main.captureStatus(),
            "business_disposition", main.currentDisposition(),
            "poll_after_ms", pollAfter(main.captureStatus()),
            "detection", summary,
            "review", main.reviewStatus() == null
                ? null
                : Map.of("status", main.reviewStatus())
        );
        // 契约中的 review 是可选对象而不是 nullable。
        if (main.reviewStatus() == null) {
            capture = without(capture, "review");
        }
        List<Map<String, Object>> attempts = jdbc.query(
            """
            SELECT attempt_no, status, worker_id, error_code,
                   started_at, finished_at
            FROM detection_attempt
            WHERE detection_task_id = ?
            ORDER BY attempt_no
            """,
            (row, index) -> immutableMap(
                "attempt_no", row.getInt("attempt_no"),
                "status", row.getString("status"),
                "worker_id", row.getString("worker_id"),
                "error_code", row.getString("error_code"),
                "started_at", instant(row, "started_at"),
                "finished_at", instant(row, "finished_at")
            ),
            detectionTaskId
        );
        List<Map<String, Object>> dispositions = jdbc.query(
            """
            SELECT disposition, reason_code, policy_version, source,
                   input_summary_sha256, created_at
            FROM disposition_record
            WHERE capture_id = ?
            ORDER BY created_at, disposition_id
            """,
            (row, index) -> immutableMap(
                "disposition", row.getString("disposition"),
                "reason_code", row.getString("reason_code"),
                "policy_version", row.getString("policy_version"),
                "source", row.getString("source"),
                "input_summary_sha256",
                    row.getString("input_summary_sha256"),
                "occurred_at", instant(row, "created_at")
            ),
            main.captureId()
        );
        List<Map<String, Object>> images = jdbc.query(
            """
            SELECT image_id, kind, bucket, object_key, object_version,
                   sha256, size_bytes, media_type, width, height,
                   metadata->>'image_role' AS image_role
            FROM image_object
            WHERE state = 'AVAILABLE'
              AND (capture_id = ? OR detection_task_id = ?)
              AND media_type IN (
                'image/png', 'image/jpeg',
                'application/json', 'application/octet-stream'
              )
            ORDER BY CASE kind WHEN 'THUMBNAIL' THEN 0 WHEN 'RAW' THEN 1 ELSE 2 END,
                     created_at,
                     image_id
            """,
            JdbcDetectionQueryRepository::mapImage,
            main.captureId(),
            detectionTaskId
        );
        Map<String, Object> versions = immutableMap(
            "pipeline_version", main.pipelineVersion(),
            "model_version", main.modelVersion(),
            "preprocessor_version", main.preprocessorVersion(),
            "algorithm_version", main.algorithmVersion(),
            "policy_version", main.policyVersion()
        );
        return immutableMap(
            "capture", capture,
            "detection", summary,
            "attempts", attempts,
            "disposition_history", dispositions,
            "images", images,
            "versions", versions
        );
    }

    private static ListRow mapListRow(ResultSet row, int index)
            throws SQLException {
        UUID id = row.getObject("detection_task_id", UUID.class);
        return new ListRow(
            id,
            row.getString("task_status"),
            row.getTimestamp("queued_at").toInstant(),
            row.getString("algorithm_outcome"),
            nullableDouble(row, "confidence"),
            row.getString("model_version")
        );
    }

    private static MainRow mapMainRow(ResultSet row, int index)
            throws SQLException {
        return new MainRow(
            row.getObject("detection_task_id", UUID.class),
            row.getString("task_status"),
            row.getObject("capture_id", UUID.class),
            row.getString("capture_status"),
            row.getString("current_disposition"),
            row.getString("algorithm_outcome"),
            nullableDouble(row, "confidence"),
            row.getString("model_version"),
            row.getString("pipeline_version"),
            row.getString("preprocessor_version"),
            row.getString("algorithm_version"),
            row.getString("policy_version"),
            row.getString("review_status")
        );
    }

    private static Map<String, Object> mapImage(
            ResultSet row,
            int index) throws SQLException {
        Map<String, Object> object = immutableMap(
            "bucket", row.getString("bucket"),
            "object_key", row.getString("object_key"),
            "object_version", emptyToNull(row.getString("object_version")),
            "sha256", row.getString("sha256").trim(),
            "size_bytes", row.getLong("size_bytes"),
            "media_type", row.getString("media_type")
        );
        Map<String, Object> image = immutableMap(
            "image_id", row.getObject("image_id", UUID.class).toString(),
            "kind", row.getString("kind"),
            "object", object,
            "width", row.getInt("width"),
            "height", row.getInt("height"),
            "image_role", row.getString("image_role")
        );
        return row.getString("image_role") == null
            ? without(image, "image_role")
            : image;
    }

    private static Map<String, Object> summary(MainRow row) {
        return immutableMap(
            "detection_task_id", row.detectionTaskId().toString(),
            "task_status", row.taskStatus(),
            "algorithm_outcome", row.algorithmOutcome(),
            "confidence", row.confidence(),
            "model_version", row.modelVersion()
        );
    }

    private static double nullableDouble(ResultSet row, String name)
            throws SQLException {
        double value = row.getDouble(name);
        return row.wasNull() ? Double.NaN : value;
    }

    private static String instant(ResultSet row, String name)
            throws SQLException {
        Timestamp value = row.getTimestamp(name);
        return value == null
            ? null
            : DateTimeFormatter.ISO_INSTANT.format(value.toInstant());
    }

    private static Object emptyToNull(String value) {
        return value == null || value.isEmpty() ? null : value;
    }

    private static int pollAfter(String status) {
        return switch (status) {
            case "FINALIZED", "FAILED" -> 0;
            case "PROCESSING", "REVIEW_PENDING" -> 1000;
            default -> 500;
        };
    }

    private static String encodeCursor(ListRow row) {
        String value = row.queuedAt().toEpochMilli()
            + ":"
            + row.detectionTaskId();
        return Base64.getUrlEncoder().withoutPadding().encodeToString(
            value.getBytes(StandardCharsets.US_ASCII)
        );
    }

    private static Cursor decodeCursor(String value) {
        try {
            String decoded = new String(
                Base64.getUrlDecoder().decode(value),
                StandardCharsets.US_ASCII
            );
            String[] parts = decoded.split(":", 2);
            if (parts.length != 2) {
                throw new IllegalArgumentException();
            }
            return new Cursor(
                Instant.ofEpochMilli(Long.parseLong(parts[0])),
                UUID.fromString(parts[1])
            );
        } catch (RuntimeException invalid) {
            throw new ContractValues.ContractInputViolation(
                "cursor 不合法"
            );
        }
    }

    private static Map<String, Object> immutableMap(Object... entries) {
        LinkedHashMap<String, Object> value = new LinkedHashMap<>();
        for (int index = 0; index < entries.length; index += 2) {
            value.put((String) entries[index], entries[index + 1]);
        }
        return Collections.unmodifiableMap(value);
    }

    private static Map<String, Object> without(
            Map<String, Object> original,
            String key) {
        LinkedHashMap<String, Object> value = new LinkedHashMap<>(original);
        value.remove(key);
        return Collections.unmodifiableMap(value);
    }

    private record Cursor(Instant queuedAt, UUID detectionTaskId) {}

    private record ListRow(
        UUID detectionTaskId,
        String taskStatus,
        Instant queuedAt,
        String algorithmOutcome,
        double confidenceValue,
        String modelVersion
    ) {
        Object confidence() {
            return Double.isNaN(confidenceValue) ? null : confidenceValue;
        }

        Map<String, Object> summary() {
            return immutableMap(
                "detection_task_id", detectionTaskId.toString(),
                "task_status", taskStatus,
                "algorithm_outcome", algorithmOutcome,
                "confidence", confidence(),
                "model_version", modelVersion
            );
        }
    }

    private record MainRow(
        UUID detectionTaskId,
        String taskStatus,
        UUID captureId,
        String captureStatus,
        String currentDisposition,
        String algorithmOutcome,
        double confidenceValue,
        String modelVersion,
        String pipelineVersion,
        String preprocessorVersion,
        String algorithmVersion,
        String policyVersion,
        String reviewStatus
    ) {
        Object confidence() {
            return Double.isNaN(confidenceValue) ? null : confidenceValue;
        }
    }
}
