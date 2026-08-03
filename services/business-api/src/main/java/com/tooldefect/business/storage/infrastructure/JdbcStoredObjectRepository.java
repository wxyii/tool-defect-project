package com.tooldefect.business.storage.infrastructure;

import java.util.Optional;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.storage.application.StoredObjectRepository;
import com.tooldefect.business.storage.application.DerivedObjectAcceptance;
import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.storage.domain.ObjectState;
import com.tooldefect.business.storage.domain.StoredObject;

@Repository
public class JdbcStoredObjectRepository implements StoredObjectRepository {
    private final JdbcTemplate jdbc;

    public JdbcStoredObjectRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Optional<StoredObject> findById(UUID imageId) {
        return findById(imageId, false);
    }

    @Override
    public Optional<StoredObject> findByIdForUpdate(UUID imageId) {
        return findById(imageId, true);
    }

    private Optional<StoredObject> findById(UUID imageId, boolean forUpdate) {
        return jdbc.query(
            """
            SELECT i.image_id,
                   i.capture_id,
                   c.station_id,
                   i.bucket,
                   i.object_key,
                   i.size_bytes,
                   i.sha256,
                   i.media_type,
                   i.state,
                   i.object_version,
                   i.width,
                   i.height,
                   i.record_version
            FROM image_object i
            JOIN capture_event c ON c.capture_id = i.capture_id
            WHERE i.image_id = ?
            """ + (forUpdate ? " FOR UPDATE OF i" : ""),
            (result, row) -> StoredObject.restore(
                result.getObject("image_id", UUID.class),
                result.getObject("capture_id", UUID.class),
                result.getObject("station_id", UUID.class),
                result.getString("bucket"),
                result.getString("object_key"),
                result.getLong("size_bytes"),
                result.getString("sha256").trim(),
                result.getString("media_type"),
                ObjectState.valueOf(result.getString("state")),
                result.getString("object_version"),
                (Integer) result.getObject("width"),
                (Integer) result.getObject("height"),
                result.getLong("record_version")
            ),
            imageId
        ).stream().findFirst();
    }

    @Override
    public void insertStaging(StoredObject object) {
        jdbc.update(
            """
            INSERT INTO image_object(
                image_id,
                capture_id,
                kind,
                bucket,
                object_key,
                sha256,
                size_bytes,
                media_type,
                state
            )
            VALUES (?, ?, 'RAW', ?, ?, ?, ?, ?, 'STAGING')
            """,
            object.imageId(),
            object.captureId(),
            object.bucket(),
            object.objectKey(),
            object.expectedSha256(),
            object.expectedSizeBytes(),
            object.expectedMediaType()
        );
    }

    @Override
    public void insertReviewMaskStaging(
            StoredObject object,
            UUID reviewTaskId,
            int expectedWidth,
            int expectedHeight) {
        int inserted = jdbc.update(
            """
            INSERT INTO image_object(
                image_id,
                capture_id,
                review_task_id,
                kind,
                bucket,
                object_key,
                sha256,
                size_bytes,
                media_type,
                state,
                metadata
            )
            VALUES (
                ?,
                ?,
                ?,
                'REVIEW_MASK',
                ?,
                ?,
                ?,
                ?,
                'image/png',
                'STAGING',
                jsonb_build_object(
                    'expected_width', CAST(? AS integer),
                    'expected_height', CAST(? AS integer)
                )
            )
            """,
            object.imageId(),
            object.captureId(),
            reviewTaskId,
            object.bucket(),
            object.objectKey(),
            object.expectedSha256(),
            object.expectedSizeBytes(),
            expectedWidth,
            expectedHeight
        );
        if (inserted != 1) {
            throw new com.tooldefect.business.shared.domain.DomainViolation(
                "人工掩膜暂存记录写入失败"
            );
        }
    }

    @Override
    public void insertDerivedAvailable(
            DerivedObjectAcceptance.DerivedObject object,
            String actualObjectVersion,
            int width,
            int height) {
        int inserted = jdbc.update(
            """
            INSERT INTO image_object(
                image_id,
                capture_id,
                detection_task_id,
                kind,
                bucket,
                object_key,
                object_version,
                sha256,
                size_bytes,
                media_type,
                width,
                height,
                state,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'AVAILABLE',
                    CAST(? AS jsonb))
            """,
            object.imageId(),
            object.captureId(),
            object.detectionTaskId(),
            object.kind(),
            object.bucket(),
            object.objectKey(),
            actualObjectVersion == null ? "" : actualObjectVersion,
            object.sha256(),
            object.sizeBytes(),
            object.mediaType(),
            width,
            height,
            CanonicalJson.encode(object.metadata())
        );
        if (inserted != 1) {
            throw new com.tooldefect.business.shared.domain.DomainViolation(
                "派生对象登记失败"
            );
        }
    }

    @Override
    public Optional<ReviewMaskSource> reviewMaskSource(
            UUID reviewTaskId,
            UUID captureId) {
        return jdbc.query(
            """
            SELECT capture.station_id,
                   source.width,
                   source.height
            FROM review_task task
            JOIN capture_event capture
              ON capture.capture_id = task.capture_id
            JOIN LATERAL (
                SELECT width, height
                FROM image_object
                WHERE capture_id = capture.capture_id
                  AND kind = 'RAW'
                  AND state = 'AVAILABLE'
                  AND width IS NOT NULL
                  AND height IS NOT NULL
                ORDER BY
                    CASE metadata->>'image_role'
                        WHEN 'primary' THEN 0
                        ELSE 1
                    END,
                    created_at,
                    image_id
                LIMIT 1
            ) source ON true
            WHERE task.review_task_id = ?
              AND task.capture_id = ?
              AND task.status IN (
                'PENDING',
                'CLAIMED',
                'SECOND_REVIEW_PENDING',
                'ESCALATED'
              )
            """,
            (row, index) -> new ReviewMaskSource(
                row.getObject("station_id", UUID.class),
                row.getInt("width"),
                row.getInt("height")
            ),
            reviewTaskId,
            captureId
        ).stream().findFirst();
    }

    @Override
    public Optional<ReviewMaskExpectation> reviewMaskExpectation(UUID imageId) {
        return jdbc.query(
            """
            SELECT review_task_id,
                   (metadata->>'expected_width')::integer AS expected_width,
                   (metadata->>'expected_height')::integer AS expected_height
            FROM image_object
            WHERE image_id = ?
              AND kind = 'REVIEW_MASK'
            """,
            (row, index) -> new ReviewMaskExpectation(
                row.getObject("review_task_id", UUID.class),
                row.getInt("expected_width"),
                row.getInt("expected_height")
            ),
            imageId
        ).stream().findFirst();
    }

    @Override
    public boolean markAvailable(
            UUID imageId,
            long expectedRecordVersion,
            String objectVersion,
            int width,
            int height) {
        return jdbc.update(
            """
            UPDATE image_object
            SET state = 'AVAILABLE',
                object_version = ?,
                width = ?,
                height = ?,
                updated_at = now(),
                record_version = record_version + 1
            WHERE image_id = ?
              AND state = 'STAGING'
              AND record_version = ?
            """,
            objectVersion == null ? "" : objectVersion,
            width,
            height,
            imageId,
            expectedRecordVersion
        ) == 1;
    }

    @Override
    public boolean markQuarantined(
            UUID imageId,
            long expectedRecordVersion,
            String reason) {
        return jdbc.update(
            """
            UPDATE image_object
            SET state = 'QUARANTINED',
                metadata = metadata || jsonb_build_object(
                    'quarantine_reason', CAST(? AS text)
                ),
                updated_at = now(),
                record_version = record_version + 1
            WHERE image_id = ?
              AND state IN ('STAGING', 'AVAILABLE')
              AND record_version = ?
            """,
            reason,
            imageId,
            expectedRecordVersion
        ) == 1;
    }
}
