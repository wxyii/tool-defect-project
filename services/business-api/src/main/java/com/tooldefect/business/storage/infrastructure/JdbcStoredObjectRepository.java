package com.tooldefect.business.storage.infrastructure;

import java.util.Optional;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.storage.application.StoredObjectRepository;
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
    public boolean captureBelongsToStation(UUID captureId, UUID stationId) {
        Boolean value = jdbc.queryForObject(
            """
            SELECT EXISTS (
                SELECT 1
                FROM capture_event
                WHERE capture_id = ?
                  AND station_id = ?
            )
            """,
            Boolean.class,
            captureId,
            stationId
        );
        return Boolean.TRUE.equals(value);
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
