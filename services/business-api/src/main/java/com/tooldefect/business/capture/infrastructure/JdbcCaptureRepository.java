package com.tooldefect.business.capture.infrastructure;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.capture.application.CaptureImageRegistration;
import com.tooldefect.business.capture.application.CaptureRegistration;
import com.tooldefect.business.capture.application.CaptureRepository;
import com.tooldefect.business.capture.application.CaptureStatusView;
import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.domain.DomainViolation;

@Repository
public class JdbcCaptureRepository implements CaptureRepository {
    private final JdbcTemplate jdbc;

    public JdbcCaptureRepository(JdbcTemplate jdbc) {
        this.jdbc = java.util.Objects.requireNonNull(jdbc);
    }

    @Override
    public void insertCapture(
            CaptureRegistration registration,
            String requestSha256) {
        String sourceType = switch (registration.triggerSource()) {
            case "HISTORICAL_IMPORT" -> "HISTORICAL_IMPORT";
            case "MANUAL" -> "MANUAL";
            case "PLC", "SENSOR" -> "ONLINE";
            default -> throw new DomainViolation("触发来源不合法");
        };
        String qualityStatus = switch (registration.qualityStatus()) {
            case "OK" -> "OK";
            case "WARNING" -> "QUALITY_WARNING";
            case "REJECTED" -> "QUALITY_REJECTED";
            default -> throw new DomainViolation("采集质量状态不合法");
        };
        int inserted = jdbc.update(
            """
            INSERT INTO capture_event(
                capture_id,
                station_id,
                trigger_id,
                client_sequence,
                source_type,
                captured_at,
                recipe_id,
                status,
                quality_status,
                attributes,
                request_digest
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'UPLOADING', ?, CAST(? AS jsonb), ?)
            """,
            registration.captureId(),
            registration.stationId(),
            registration.triggerId(),
            registration.clientSequence(),
            sourceType,
            Timestamp.from(registration.capturedAt()),
            registration.recipeId(),
            qualityStatus,
            CanonicalJson.encode(java.util.Map.of(
                "trigger_source", registration.triggerSource(),
                "quality_warnings", registration.qualityWarnings()
            )),
            requestSha256
        );
        if (inserted != 1) {
            throw new DomainViolation("中央采集事件创建失败");
        }
    }

    @Override
    public void attachImageMetadata(
            UUID imageId,
            CaptureImageRegistration image) {
        int updated = jdbc.update(
            """
            UPDATE image_object
            SET metadata = metadata || CAST(? AS jsonb),
                width = ?,
                height = ?,
                updated_at = now(),
                record_version = record_version + 1
            WHERE image_id = ?
              AND state = 'STAGING'
            """,
            CanonicalJson.encode(java.util.Map.of(
                "client_image_id", image.clientImageId(),
                "image_role", image.imageRole(),
                "source_file_name", image.fileName(),
                "required", true
            )),
            image.width(),
            image.height(),
            imageId
        );
        if (updated != 1) {
            throw new DomainViolation("图片角色元数据登记失败");
        }
    }

    @Override
    public boolean allImagesAvailable(UUID captureId) {
        Boolean value = jdbc.queryForObject(
            """
            SELECT EXISTS (
                SELECT 1 FROM image_object
                WHERE capture_id = ? AND kind = 'RAW'
            ) AND NOT EXISTS (
                SELECT 1 FROM image_object
                WHERE capture_id = ?
                  AND kind = 'RAW'
                  AND state <> 'AVAILABLE'
            )
            """,
            Boolean.class,
            captureId,
            captureId
        );
        return Boolean.TRUE.equals(value);
    }

    @Override
    public void markReady(UUID captureId) {
        int updated = jdbc.update(
            """
            UPDATE capture_event
            SET status = 'READY',
                updated_at = now(),
                record_version = record_version + 1
            WHERE capture_id = ?
              AND status = 'UPLOADING'
            """,
            captureId
        );
        if (updated == 0) {
            String status = jdbc.queryForObject(
                "SELECT status FROM capture_event WHERE capture_id = ?",
                String.class,
                captureId
            );
            if (!"READY".equals(status)) {
                throw new DomainViolation("采集状态不能推进到 READY");
            }
        }
    }

    @Override
    public SubmissionContext lockReadySubmission(
            UUID captureId,
            UUID stationId) {
        var context = jdbc.query(
            """
            SELECT c.capture_id,
                   c.station_id,
                   c.recipe_id,
                   c.captured_at,
                   p.pipeline_id,
                   p.version AS pipeline_version,
                   p.config_sha256,
                   p.preprocessor_version,
                   p.algorithm_version,
                   mv.version AS model_version,
                   mv.artifact_sha256 AS model_sha256
            FROM capture_event c
            JOIN station s ON s.station_id = c.station_id
            JOIN pipeline_version p ON p.pipeline_id = s.active_pipeline_id
            JOIN model_version mv ON mv.model_version_id = p.model_version_id
            WHERE c.capture_id = ?
              AND c.station_id = ?
              AND c.status = 'READY'
              AND p.status = 'APPROVED'
              AND mv.approval_state = 'APPROVED'
            FOR UPDATE OF c
            """,
            (row, rowNumber) -> new SubmissionContext(
                row.getObject("capture_id", UUID.class),
                row.getObject("station_id", UUID.class),
                row.getObject("recipe_id", UUID.class),
                row.getTimestamp("captured_at").toInstant(),
                row.getObject("pipeline_id", UUID.class),
                row.getString("pipeline_version"),
                row.getString("config_sha256").trim(),
                row.getString("preprocessor_version"),
                row.getString("algorithm_version"),
                row.getString("model_version"),
                row.getString("model_sha256").trim(),
                List.of()
            ),
            captureId,
            stationId
        ).stream().findFirst().orElseThrow(() ->
            new DomainViolation(
                "采集未 READY、流水线未批准或设备无权提交"
            )
        );
        List<ImageReference> images = jdbc.query(
            """
            SELECT image_id,
                   COALESCE(metadata->>'image_role', 'PRIMARY') AS image_role,
                   kind,
                   bucket,
                   object_key,
                   object_version,
                   sha256,
                   size_bytes,
                   media_type,
                   width,
                   height
            FROM image_object
            WHERE capture_id = ?
              AND kind = 'RAW'
              AND state = 'AVAILABLE'
            ORDER BY image_id
            """,
            (row, rowNumber) -> new ImageReference(
                row.getObject("image_id", UUID.class),
                row.getString("image_role"),
                row.getString("kind"),
                row.getString("bucket"),
                row.getString("object_key"),
                row.getString("object_version"),
                row.getString("sha256").trim(),
                row.getLong("size_bytes"),
                row.getString("media_type"),
                row.getInt("width"),
                row.getInt("height")
            ),
            captureId
        );
        return new SubmissionContext(
            context.captureId(),
            context.stationId(),
            context.recipeId(),
            context.capturedAt(),
            context.pipelineId(),
            context.pipelineVersion(),
            context.configSha256(),
            context.preprocessorVersion(),
            context.algorithmVersion(),
            context.modelVersion(),
            context.modelSha256(),
            images
        );
    }

    @Override
    public void insertDetectionTask(
            UUID detectionTaskId,
            SubmissionContext context) {
        int inserted = jdbc.update(
            """
            INSERT INTO detection_task(
                detection_task_id,
                capture_id,
                pipeline_id,
                purpose,
                status,
                priority
            )
            VALUES (?, ?, ?, 'PRODUCTION', 'QUEUED', 10)
            """,
            detectionTaskId,
            context.captureId(),
            context.pipelineId()
        );
        if (inserted != 1) {
            throw new DomainViolation("检测任务创建失败");
        }
    }

    @Override
    public void markSubmitted(UUID captureId) {
        int updated = jdbc.update(
            """
            UPDATE capture_event
            SET status = 'SUBMITTED',
                updated_at = now(),
                record_version = record_version + 1
            WHERE capture_id = ?
              AND status = 'READY'
            """,
            captureId
        );
        if (updated != 1) {
            throw new DomainViolation("采集提交发生并发冲突");
        }
    }

    @Override
    public Optional<CaptureStatusView> findStatus(
            UUID captureId,
            UUID stationId) {
        return jdbc.query(
            """
            SELECT c.capture_id,
                   c.status AS capture_status,
                   c.current_disposition,
                   t.detection_task_id,
                   t.status AS task_status,
                   r.algorithm_outcome,
                   r.confidence,
                   mv.version AS model_version,
                   review.status AS review_status
            FROM capture_event c
            LEFT JOIN LATERAL (
                SELECT *
                FROM detection_task
                WHERE capture_id = c.capture_id
                  AND purpose = 'PRODUCTION'
                ORDER BY created_at DESC
                LIMIT 1
            ) t ON true
            LEFT JOIN detection_result r
                ON r.detection_task_id = t.detection_task_id
            LEFT JOIN pipeline_version p ON p.pipeline_id = t.pipeline_id
            LEFT JOIN model_version mv ON mv.model_version_id = p.model_version_id
            LEFT JOIN LATERAL (
                SELECT status
                FROM review_task
                WHERE capture_id = c.capture_id
                ORDER BY created_at DESC
                LIMIT 1
            ) review ON true
            WHERE c.capture_id = ?
              AND c.station_id = ?
            """,
            JdbcCaptureRepository::mapStatus,
            captureId,
            stationId
        ).stream().findFirst();
    }

    @Override
    public void updateHeartbeat(
            UUID deviceId,
            UUID stationId,
            String agentVersion,
            java.time.Instant reportedAt,
            java.util.Map<String, Object> snapshot) {
        String camera = String.valueOf(snapshot.get("camera_status"));
        String plc = String.valueOf(snapshot.get("plc_status"));
        String status = "ONLINE".equals(camera) && "ONLINE".equals(plc)
            ? "ONLINE"
            : "DEGRADED";
        int updated = jdbc.update(
            """
            UPDATE device
            SET agent_version = ?,
                last_seen_at = ?,
                status = ?,
                heartbeat_snapshot = CAST(? AS jsonb),
                updated_at = now(),
                record_version = record_version + 1
            WHERE device_id = ?
              AND station_id = ?
              AND status <> 'REVOKED'
            """,
            agentVersion,
            Timestamp.from(reportedAt),
            status,
            CanonicalJson.encode(snapshot),
            deviceId,
            stationId
        );
        if (updated != 1) {
            throw new DomainViolation("设备不存在、已撤销或不在身份工位范围");
        }
    }

    private static CaptureStatusView mapStatus(
            ResultSet row,
            int rowNumber) throws SQLException {
        return new CaptureStatusView(
            row.getObject("capture_id", UUID.class),
            row.getString("capture_status"),
            row.getString("current_disposition"),
            row.getObject("detection_task_id", UUID.class),
            row.getString("task_status"),
            row.getString("algorithm_outcome"),
            nullableDouble(row, "confidence"),
            row.getString("model_version"),
            row.getString("review_status")
        );
    }

    private static Double nullableDouble(ResultSet row, String column)
            throws SQLException {
        double value = row.getDouble(column);
        return row.wasNull() ? null : value;
    }
}
