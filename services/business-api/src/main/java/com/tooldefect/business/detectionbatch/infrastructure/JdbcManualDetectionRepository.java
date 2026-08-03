package com.tooldefect.business.detectionbatch.infrastructure;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.detectionbatch.application.ManualDetectionRepository;
import com.tooldefect.business.detectionbatch.application.ManualDetectionViolation;
import com.tooldefect.business.detectionbatch.application.ManualDetectionViolation.Kind;

@Repository
public class JdbcManualDetectionRepository implements ManualDetectionRepository {
    private final JdbcTemplate jdbc;

    public JdbcManualDetectionRepository(JdbcTemplate jdbc) {
        this.jdbc = java.util.Objects.requireNonNull(jdbc);
    }

    @Override
    public BatchView createBatch(UUID ownerId, String usageStage, String usageStageNote) {
        UUID id = UUID.randomUUID();
        jdbc.update("""
            INSERT INTO detection_batch_v2(batch_id, batch_no, source, created_by,
              usage_stage, usage_stage_note, status)
            VALUES (?, 'JC-' || to_char(now() AT TIME ZONE 'UTC', 'YYYYMMDD') || '-' ||
              lpad(nextval('detection_batch_number_seq')::text, 5, '0'),
              'MANUAL_UPLOAD', ?, ?, ?, 'DRAFT')
            """, id, ownerId, usageStage, usageStageNote);
        return requireBatch(id, ownerId, false, true);
    }

    @Override
    public UploadIntent addItem(UUID batchId, UUID itemId, UUID ownerId, String fileName,
            long sizeBytes, String mediaType, String sha256, String bucket,
            String objectKey, Instant expiresAt, int maximumItems) {
        BatchView batch = requireBatch(batchId, ownerId, false, true);
        if (!List.of("DRAFT", "UPLOADING", "READY").contains(batch.status())) {
            throw violation(Kind.CONFLICT, "批次已提交，不能增加图片项");
        }
        Integer count = jdbc.queryForObject(
            "SELECT count(*) FROM detection_batch_item_v2 WHERE batch_id = ?", Integer.class, batchId);
        if (count == null || count >= maximumItems) {
            throw violation(Kind.CONFLICT, "批次图片数量已达到配额");
        }
        UUID uploadId = UUID.randomUUID();
        try {
            jdbc.update("""
                INSERT INTO image_object(image_id, kind, bucket, object_key, sha256,
                  size_bytes, media_type, state, metadata)
                VALUES (?, 'RAW', ?, ?, ?, ?, ?, 'STAGING',
                  jsonb_build_object('source', 'MANUAL_UPLOAD', 'file_name', ?))
                """, itemId, bucket, objectKey, sha256, sizeBytes, mediaType, fileName);
            jdbc.update("""
                INSERT INTO detection_batch_item_v2(batch_item_id, batch_id, image_id, status)
                VALUES (?, ?, ?, 'UPLOADING')
                """, itemId, batchId, itemId);
            jdbc.update("""
                INSERT INTO manual_batch_upload_v2(upload_id, batch_item_id, owner_id,
                  file_name, expected_sha256, expected_size_bytes, expected_media_type,
                  bucket, object_key, status, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'AUTHORIZED', ?)
                """, uploadId, itemId, ownerId, fileName, sha256, sizeBytes,
                mediaType, bucket, objectKey, Timestamp.from(expiresAt));
        } catch (DuplicateKeyException conflict) {
            throw violation(Kind.CONFLICT, "图片对象键或摘要发生冲突");
        }
        return findUpload(batchId, itemId, ownerId).orElseThrow();
    }

    @Override
    public Optional<UploadIntent> findUpload(UUID batchId, UUID itemId, UUID ownerId) {
        return jdbc.query("""
            SELECT u.upload_id, u.owner_id, u.file_name, u.expected_size_bytes,
              u.expected_media_type, u.expected_sha256, u.expires_at,
              i.batch_item_id, i.batch_id, o.bucket, o.object_key, o.object_version,
              o.sha256, o.size_bytes, o.media_type, i.status, i.algorithm_outcome,
              i.quick_review_decision, i.created_at, i.updated_at
            FROM manual_batch_upload_v2 u
            JOIN detection_batch_item_v2 i ON i.batch_item_id = u.batch_item_id
            JOIN detection_batch_v2 b ON b.batch_id = i.batch_id
            JOIN image_object o ON o.image_id = i.image_id
            WHERE i.batch_id = ? AND i.batch_item_id = ? AND b.created_by = ?
            """, (row, n) -> new UploadIntent(
                row.getObject("upload_id", UUID.class), item(row),
                row.getObject("owner_id", UUID.class), row.getString("file_name"),
                row.getLong("expected_size_bytes"), row.getString("expected_media_type"),
                row.getString("expected_sha256").trim(), row.getTimestamp("expires_at").toInstant()
            ), batchId, itemId, ownerId).stream().findFirst();
    }

    @Override
    public ItemView confirmUpload(UUID batchId, UUID itemId, UUID ownerId,
            String objectVersion, int width, int height) {
        UploadIntent upload = findUpload(batchId, itemId, ownerId)
            .orElseThrow(() -> violation(Kind.NOT_FOUND, "图片项不存在"));
        if (upload.expiresAt().isBefore(Instant.now())) {
            throw violation(Kind.EXPIRED, "上传票据已过期");
        }
        jdbc.update("""
            UPDATE image_object SET state = 'AVAILABLE', object_version = ?, width = ?,
              height = ?, updated_at = now(), record_version = record_version + 1
            WHERE image_id = ? AND state = 'STAGING'
            """, objectVersion == null ? "" : objectVersion, width, height, itemId);
        jdbc.update("""
            UPDATE manual_batch_upload_v2 SET status = 'CONFIRMED', confirmed_at = now(),
              updated_at = now(), record_version = record_version + 1
            WHERE batch_item_id = ? AND status = 'AUTHORIZED'
            """, itemId);
        jdbc.update("""
            UPDATE detection_batch_item_v2 SET status = 'READY', updated_at = now(),
              record_version = record_version + 1
            WHERE batch_item_id = ? AND status = 'UPLOADING'
            """, itemId);
        return findItem(batchId, itemId, ownerId, false).orElseThrow();
    }

    @Override
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void recordUploadFailure(UUID batchId, UUID itemId, UUID ownerId, String errorCode) {
        UploadIntent upload = findUpload(batchId, itemId, ownerId)
            .orElseThrow(() -> violation(Kind.NOT_FOUND, "图片项不存在"));
        jdbc.update("UPDATE image_object SET state = 'ORPHANED', updated_at = now() WHERE image_id = ?", itemId);
        jdbc.update("UPDATE manual_batch_upload_v2 SET status = 'FAILED', updated_at = now() WHERE batch_item_id = ?", itemId);
        jdbc.update("UPDATE detection_batch_item_v2 SET status = 'FAILED', updated_at = now(), record_version = record_version + 1 WHERE batch_item_id = ?", itemId);
        jdbc.update("""
            INSERT INTO r3_compensation_event(compensation_id, batch_id, batch_item_id,
              operation, status, error_code, detail_digest)
            VALUES (?, ?, ?, 'CONFIRM_UPLOAD', 'HOLD', ?, md5(?) || md5(?))
            """, UUID.randomUUID(), batchId, itemId, errorCode,
            upload.expectedSha256(), upload.expectedSha256() + ':' + errorCode);
    }

    @Override
    public void deleteItem(UUID batchId, UUID itemId, UUID ownerId, long expectedVersion) {
        BatchView batch = requireBatch(batchId, ownerId, false, true);
        if (batch.version() != expectedVersion || !List.of("DRAFT", "UPLOADING", "READY").contains(batch.status())) {
            throw violation(Kind.CONFLICT, "批次版本冲突或已提交");
        }
        int changed = jdbc.update("UPDATE image_object SET state = 'ORPHANED', updated_at = now() WHERE image_id = ? AND EXISTS (SELECT 1 FROM detection_batch_item_v2 i WHERE i.image_id = image_object.image_id AND i.batch_id = ?)", itemId, batchId);
        if (changed != 1) throw violation(Kind.NOT_FOUND, "图片项不存在");
        jdbc.update("DELETE FROM manual_batch_upload_v2 WHERE batch_item_id = ?", itemId);
        jdbc.update("DELETE FROM detection_batch_item_v2 WHERE batch_item_id = ?", itemId);
    }

    @Override
    public BatchView submit(UUID batchId, UUID ownerId, long expectedVersion, String key) {
        BatchView batch = requireBatch(batchId, ownerId, false, true);
        if (batch.version() != expectedVersion) throw violation(Kind.CONFLICT, "批次版本冲突");
        if (!"READY".equals(batch.status()) || batch.counts().total() == 0) {
            throw violation(Kind.CONFLICT, "批次存在未确认图片项");
        }
        jdbc.update("""
            INSERT INTO detection_task_v2(detection_task_id, batch_item_id, status, submit_idempotency_key)
            SELECT gen_random_uuid(), batch_item_id, 'QUEUED', ?
            FROM detection_batch_item_v2 WHERE batch_id = ? AND status = 'READY'
            ON CONFLICT (batch_item_id) DO NOTHING
            """, key, batchId);
        jdbc.update("""
            UPDATE detection_batch_item_v2 SET status = 'QUEUED', updated_at = now(),
              record_version = record_version + 1 WHERE batch_id = ? AND status = 'READY'
            """, batchId);
        return requireBatch(batchId, ownerId, false, false);
    }

    @Override
    public List<TaskDispatch> queuedTasks(UUID batchId, String key) {
        return jdbc.query("""
            SELECT t.detection_task_id, i.batch_item_id, o.bucket, o.object_key,
              o.object_version, o.sha256, o.size_bytes, o.media_type
            FROM detection_task_v2 t
            JOIN detection_batch_item_v2 i ON i.batch_item_id = t.batch_item_id
            JOIN image_object o ON o.image_id = i.image_id
            WHERE i.batch_id = ? AND t.submit_idempotency_key = ?
            ORDER BY i.created_at, i.batch_item_id
            """, (row, number) -> new TaskDispatch(
                row.getObject("detection_task_id", UUID.class),
                row.getObject("batch_item_id", UUID.class),
                row.getString("bucket"), row.getString("object_key"),
                row.getString("object_version"), row.getString("sha256").trim(),
                row.getLong("size_bytes"), row.getString("media_type")),
            batchId, key);
    }

    @Override
    public Optional<BatchView> findBatch(UUID batchId, UUID actorId, boolean all) {
        return batches("WHERE batch_id = ? AND (? OR created_by = ?)", batchId, all, actorId).stream().findFirst();
    }

    @Override
    public Optional<ItemView> findItem(UUID batchId, UUID itemId, UUID actorId, boolean all) {
        return jdbc.query("""
            SELECT i.batch_item_id, i.batch_id, o.bucket, o.object_key, o.object_version,
              o.sha256, o.size_bytes, o.media_type, i.status, i.algorithm_outcome,
              i.quick_review_decision, i.created_at, i.updated_at
            FROM detection_batch_item_v2 i JOIN detection_batch_v2 b ON b.batch_id=i.batch_id
            JOIN image_object o ON o.image_id=i.image_id
            WHERE i.batch_id=? AND i.batch_item_id=? AND (? OR b.created_by=?)
            """, (row,n)->item(row), batchId, itemId, all, actorId).stream().findFirst();
    }

    @Override
    public Page list(UUID actorId, boolean all, Instant before, UUID beforeId, int limit) {
        List<BatchView> result = batches("""
            WHERE (? OR created_by = ?) AND (?::timestamptz IS NULL OR (created_at, batch_id) < (?::timestamptz, ?::uuid))
            ORDER BY created_at DESC, batch_id DESC LIMIT ?
            """, all, actorId, before == null ? null : Timestamp.from(before),
            before == null ? null : Timestamp.from(before), beforeId, limit + 1);
        String cursor = null;
        if (result.size() > limit) {
            BatchView last = result.get(limit - 1);
            cursor = last.createdAt() + "|" + last.batchId();
            result = result.subList(0, limit);
        }
        return new Page(List.copyOf(result), cursor);
    }

    @Override
    @Transactional
    public List<OrphanObject> claimExpiredOrphans(Instant cutoff, int limit) {
        List<OrphanObject> orphans = jdbc.query("""
            SELECT i.batch_id,u.batch_item_id,u.bucket,u.object_key
            FROM manual_batch_upload_v2 u JOIN detection_batch_item_v2 i ON i.batch_item_id=u.batch_item_id
            WHERE u.status='AUTHORIZED' AND u.expires_at < ?
            ORDER BY expires_at, upload_id LIMIT ? FOR UPDATE SKIP LOCKED
            """, (row, number) -> new OrphanObject(row.getObject("batch_id",UUID.class),
                row.getObject("batch_item_id",UUID.class),row.getString("bucket"),row.getString("object_key")),
            Timestamp.from(cutoff), limit);
        for (OrphanObject orphan : orphans) {
            UUID itemId = orphan.itemId();
            jdbc.update("UPDATE manual_batch_upload_v2 SET status='EXPIRED', updated_at=now(), record_version=record_version+1 WHERE batch_item_id=?", itemId);
            jdbc.update("UPDATE image_object SET state='ORPHANED', updated_at=now(), record_version=record_version+1 WHERE image_id=(SELECT image_id FROM detection_batch_item_v2 WHERE batch_item_id=?)", itemId);
            jdbc.update("UPDATE detection_batch_item_v2 SET status='CANCELLED', updated_at=now(), record_version=record_version+1 WHERE batch_item_id=?", itemId);
            recordOrphanCleanup(orphan,false,"TD-STORAGE-ORPHAN-CLEANUP-PENDING");
        }
        return List.copyOf(orphans);
    }

    @Override
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void recordOrphanCleanup(OrphanObject orphan, boolean resolved, String errorCode) {
        jdbc.update("""
            INSERT INTO r3_compensation_event(compensation_id,batch_id,batch_item_id,
              operation,status,error_code,detail_digest,resolved_at)
            VALUES (gen_random_uuid(),?,?,'ORPHAN_CLEANUP',?,?,md5(? )||md5(?),
              CASE WHEN ? THEN now() ELSE NULL END)
            """,orphan.batchId(),orphan.itemId(),resolved?"RESOLVED":"PENDING",errorCode,
            orphan.itemId().toString(),"orphan:"+orphan.itemId()+":"+errorCode,resolved);
    }

    private BatchView requireBatch(UUID id, UUID actor, boolean all, boolean lock) {
        String suffix = lock ? " FOR UPDATE" : "";
        return batches("WHERE batch_id=? AND (? OR created_by=?)" + suffix, id, all, actor)
            .stream().findFirst().orElseThrow(() -> violation(Kind.NOT_FOUND, "批次不存在或不可访问"));
    }

    private List<BatchView> batches(String clause, Object... args) {
        return jdbc.query("""
            SELECT batch_id,batch_no,created_by,usage_stage,usage_stage_note,status,
              total_count,completed_count,defect_suspected_count,normal_count,
              inconclusive_count,quality_rejected_count,technical_failed_count,
              created_at,updated_at,record_version FROM detection_batch_v2
            """ + clause, (row,n)->new BatchView(
                row.getObject("batch_id",UUID.class),row.getString("batch_no"),
                row.getObject("created_by",UUID.class),row.getString("usage_stage"),
                row.getString("usage_stage_note"),row.getString("status"),
                new Counts(row.getInt("total_count"),row.getInt("completed_count"),
                    row.getInt("defect_suspected_count"),row.getInt("normal_count"),
                    row.getInt("inconclusive_count"),row.getInt("quality_rejected_count"),
                    row.getInt("technical_failed_count")),row.getTimestamp("created_at").toInstant(),
                row.getTimestamp("updated_at").toInstant(),row.getLong("record_version")), args);
    }

    private static ItemView item(java.sql.ResultSet row) throws java.sql.SQLException {
        return new ItemView(row.getObject("batch_item_id",UUID.class),row.getObject("batch_id",UUID.class),
            row.getString("bucket"),row.getString("object_key"),row.getString("object_version"),
            row.getString("sha256").trim(),row.getLong("size_bytes"),row.getString("media_type"),
            row.getString("status"),row.getString("algorithm_outcome"),row.getString("quick_review_decision"),
            row.getTimestamp("created_at").toInstant(),row.getTimestamp("updated_at").toInstant());
    }

    private static ManualDetectionViolation violation(Kind kind, String message) {
        return new ManualDetectionViolation(kind, message);
    }
}
