package com.tooldefect.business.detectionbatch.infrastructure;

import java.util.UUID;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.detectionbatch.application.ManualDetectionViolation;
import com.tooldefect.business.detectionbatch.application.ProductionDetectionRepository;

@Repository
public class JdbcProductionDetectionRepository implements ProductionDetectionRepository {
    private final JdbcTemplate jdbc;

    public JdbcProductionDetectionRepository(JdbcTemplate jdbc) {
        this.jdbc = java.util.Objects.requireNonNull(jdbc);
    }

    @Override
    public Acceptance create(UUID captureId, String deviceSubject, Image image, String key) {
        Acceptance existing = findExisting(captureId, image.sha256());
        if (existing != null) {
            return existing;
        }
        UUID batchId = UUID.randomUUID();
        UUID itemId = UUID.randomUUID();
        UUID taskId = UUID.randomUUID();
        try {
            jdbc.update("""
                INSERT INTO image_object(image_id, kind, bucket, object_key, object_version,
                  sha256, size_bytes, media_type, width, height, state, metadata)
                VALUES (?, 'RAW', ?, ?, ?, ?, ?, ?, ?, ?, 'AVAILABLE',
                  jsonb_build_object('source','PRODUCTION_CAPTURE','device_subject',?))
                """, itemId, image.bucket(), image.objectKey(),
                image.objectVersion() == null ? "" : image.objectVersion(), image.sha256(),
                image.sizeBytes(), image.mediaType(), image.width(), image.height(), deviceSubject);
            jdbc.update("""
                INSERT INTO detection_batch_v2(batch_id, batch_no, source, usage_stage,
                  status, total_count)
                VALUES (?, 'CX-' || to_char(now() AT TIME ZONE 'UTC', 'YYYYMMDD') || '-' ||
                  lpad(nextval('detection_batch_number_seq')::text, 5, '0'),
                  'PRODUCTION_CAPTURE', 'UNSPECIFIED', 'PROCESSING', 1)
                """, batchId);
            jdbc.update("""
                INSERT INTO detection_batch_item_v2(batch_item_id, batch_id, image_id, status)
                VALUES (?, ?, ?, 'QUEUED')
                """, itemId, batchId, itemId);
            jdbc.update("""
                INSERT INTO detection_task_v2(detection_task_id, batch_item_id, status,
                  submit_idempotency_key) VALUES (?, ?, 'QUEUED', ?)
                """, taskId, itemId, key);
            jdbc.update("""
                INSERT INTO production_capture_item_v2(capture_id, batch_item_id,
                  device_subject, source_sha256) VALUES (?, ?, ?, ?)
                """, captureId, itemId, deviceSubject, image.sha256());
        } catch (DuplicateKeyException conflict) {
            throw new ManualDetectionViolation(
                ManualDetectionViolation.Kind.CONFLICT,
                "产线对象键或唯一标识发生并发冲突");
        }
        return new Acceptance(captureId, batchId, itemId, taskId, "QUEUED", image);
    }

    private Acceptance findExisting(UUID captureId, String expectedSha256) {
        var rows = jdbc.query("""
            SELECT p.capture_id, i.batch_id, i.batch_item_id, t.detection_task_id,
              t.status, o.bucket, o.object_key, o.object_version, o.sha256,
              o.size_bytes, o.media_type, o.width, o.height
            FROM production_capture_item_v2 p
            JOIN detection_batch_item_v2 i ON i.batch_item_id=p.batch_item_id
            JOIN detection_task_v2 t ON t.batch_item_id=i.batch_item_id
            JOIN image_object o ON o.image_id=i.image_id WHERE p.capture_id=?
            """, (row, number) -> {
                String actual = row.getString("sha256").trim();
                if (!actual.equals(expectedSha256)) {
                    throw new ManualDetectionViolation(
                        ManualDetectionViolation.Kind.CONFLICT,
                        "相同 capture_id 的产线对象哈希冲突");
                }
                return new Acceptance(row.getObject("capture_id",UUID.class),
                    row.getObject("batch_id",UUID.class), row.getObject("batch_item_id",UUID.class),
                    row.getObject("detection_task_id",UUID.class), row.getString("status"),
                    new Image(row.getString("bucket"), row.getString("object_key"),
                        row.getString("object_version"), actual, row.getLong("size_bytes"),
                        row.getString("media_type"), row.getInt("width"), row.getInt("height")));
            }, captureId);
        return rows.isEmpty() ? null : rows.getFirst();
    }
}
