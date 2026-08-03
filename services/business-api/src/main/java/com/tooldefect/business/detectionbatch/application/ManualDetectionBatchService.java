package com.tooldefect.business.detectionbatch.application;

import java.time.Clock;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.audit.domain.AuditRecord;
import com.tooldefect.business.detectionbatch.application.ManualDetectionViolation.Kind;
import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.storage.application.ObjectStoragePort;

public class ManualDetectionBatchService {
    private static final Set<String> STAGES = Set.of("NEW_BLADE", "AFTER_ONE_WHEEL",
        "AFTER_TWO_WHEELS", "AFTER_THREE_WHEELS", "OTHER", "UNSPECIFIED");
    private final ManualDetectionRepository repository;
    private final ObjectStoragePort storage;
    private final IdempotencyService idempotency;
    private final AuditTrail audit;
    private final ManualDetectionSettings properties;
    private final Clock clock;

    public ManualDetectionBatchService(ManualDetectionRepository repository,
            ObjectStoragePort storage, IdempotencyService idempotency, AuditTrail audit,
            ManualDetectionSettings properties, Clock clock) {
        this.repository = java.util.Objects.requireNonNull(repository);
        this.storage = java.util.Objects.requireNonNull(storage);
        this.idempotency = java.util.Objects.requireNonNull(idempotency);
        this.audit = java.util.Objects.requireNonNull(audit);
        this.properties = java.util.Objects.requireNonNull(properties);
        this.clock = java.util.Objects.requireNonNull(clock);
    }

    public Map<String,Object> capabilities() {
        return Map.of("enabled", properties.enabled(), "maximum_items_per_batch",
            properties.maximumItemsPerBatch(), "maximum_object_bytes", properties.maximumObjectBytes(),
            "allowed_media_types", properties.allowedMediaTypes(), "upload_ttl_seconds",
            properties.uploadTtl().toSeconds());
    }

    @Transactional
    public IdempotencyService.Response create(UUID actor, String key, String stage, String note,
            Map<String,Object> request, String requestId, String traceId) {
        requireEnabled();
        if (!STAGES.contains(stage) || note != null && note.length() > 200) {
            throw violation(Kind.INTEGRITY, "使用阶段不合法");
        }
        return idempotency.execute("v2.manual-batch.create", actor.toString(), key, request, () -> {
            var batch = repository.createBatch(actor, stage, note);
            audit(actor, "MANUAL_BATCH_CREATE", batch.batchId(), null, digest(batch), requestId, traceId);
            return new IdempotencyService.Response(201, batch(batch));
        });
    }

    @Transactional
    public IdempotencyService.Response addItem(UUID actor, UUID batchId, String key,
            String fileName, long size, String mediaType, String sha256,
            Map<String,Object> request, String requestId, String traceId) {
        requireEnabled();
        if (fileName == null || fileName.isBlank() || fileName.length() > 255
                || fileName.contains("/") || fileName.contains("\\")
                || size <= 0 || size > properties.maximumObjectBytes()
                || !properties.allowedMediaTypes().contains(mediaType)
                || sha256 == null || !sha256.matches("[0-9a-f]{64}")) {
            throw violation(Kind.INTEGRITY, "图片元数据不合法");
        }
        return idempotency.execute("v2.manual-batch.add-item:" + batchId, actor.toString(), key, request, () -> {
            UUID itemId = UUID.randomUUID();
            String extension = "image/png".equals(mediaType) ? ".png" : ".jpg";
            String objectKey = properties.objectPrefix() + "/" + actor + "/" + batchId + "/" + itemId + extension;
            Instant expiresAt = Instant.now(clock).plus(properties.uploadTtl());
            var intent = repository.addItem(batchId, itemId, actor, fileName, size, mediaType, sha256,
                propertiesObjectBucket(), objectKey, expiresAt, properties.maximumItemsPerBatch());
            var ticket = storage.authorizeUpload(intent.item().bucket(), intent.item().objectKey(),
                size, sha256, mediaType, Map.of("batch-id", batchId.toString(),
                "batch-item-id", intent.item().itemId().toString()), properties.uploadTtl());
            Map<String,Object> body = new LinkedHashMap<>(item(intent.item()));
            body.put("upload", Map.of("method", ticket.method(), "url", ticket.url().toString(),
                "headers", ticket.headers(), "expires_at", ticket.expiresAt().toString()));
            audit(actor, "MANUAL_BATCH_ITEM_ADD", batchId, null, digest(intent.item()), requestId, traceId);
            return new IdempotencyService.Response(201, body);
        });
    }

    @Transactional
    public IdempotencyService.Response complete(UUID actor, UUID batchId, UUID itemId,
            String key, String sha256, long size, Map<String,Object> request,
            String requestId, String traceId) {
        requireEnabled();
        return idempotency.execute("v2.manual-batch.complete:" + itemId, actor.toString(), key, request, () -> {
            var intent = repository.findUpload(batchId, itemId, actor)
                .orElseThrow(() -> violation(Kind.NOT_FOUND, "图片项不存在"));
            if (Instant.now(clock).isAfter(intent.expiresAt())) {
                repository.recordUploadFailure(batchId, itemId, actor, "TD-STORAGE-EXPIRED-001");
                throw violation(Kind.EXPIRED, "上传票据已过期");
            }
            ObjectStoragePort.ObjectHead head;
            try {
                head = storage.head(intent.item().bucket(), intent.item().objectKey());
            } catch (RuntimeException failure) {
                repository.recordUploadFailure(batchId, itemId, actor, "TD-STORAGE-HEAD-FAILED");
                throw failure;
            }
            if (!intent.expectedSha256().equals(sha256) || intent.expectedSizeBytes() != size
                    || !sha256.equals(head.sha256()) || size != head.sizeBytes()
                    || !intent.expectedMediaType().equalsIgnoreCase(head.mediaType())) {
                repository.recordUploadFailure(batchId, itemId, actor, "TD-STORAGE-INTEGRITY-001");
                throw violation(Kind.INTEGRITY, "对象头、大小、媒体类型或 SHA-256 冲突");
            }
            var confirmed = repository.confirmUpload(batchId, itemId, actor,
                head.objectVersion(), head.width(), head.height());
            audit(actor, "MANUAL_BATCH_ITEM_CONFIRM", batchId, null, digest(confirmed), requestId, traceId);
            return new IdempotencyService.Response(200, item(confirmed));
        });
    }

    @Transactional
    public void delete(UUID actor, UUID batchId, UUID itemId, long expectedVersion,
            String requestId, String traceId) {
        requireEnabled();
        repository.deleteItem(batchId, itemId, actor, expectedVersion);
        audit(actor, "MANUAL_BATCH_ITEM_DELETE", batchId, null, null, requestId, traceId);
    }

    @Transactional
    public IdempotencyService.Response submit(UUID actor, UUID batchId, String key,
            long expectedVersion, Map<String,Object> request, String requestId, String traceId) {
        requireEnabled();
        return idempotency.execute("v2.manual-batch.submit:" + batchId, actor.toString(), key, request, () -> {
            var before = repository.findBatch(batchId, actor, false)
                .orElseThrow(() -> violation(Kind.NOT_FOUND, "批次不存在"));
            var after = repository.submit(batchId, actor, expectedVersion, key);
            audit(actor, "MANUAL_BATCH_SUBMIT", batchId, digest(before), digest(after), requestId, traceId);
            return new IdempotencyService.Response(202, batch(after));
        });
    }

    public Map<String,Object> getBatch(UUID actor, boolean all, UUID batchId) {
        return batch(repository.findBatch(batchId, actor, all)
            .orElseThrow(() -> violation(Kind.NOT_FOUND, "批次不存在或不可访问")));
    }

    public Map<String,Object> getItem(UUID actor, boolean all, UUID batchId, UUID itemId) {
        var value = repository.findItem(batchId, itemId, actor, all)
            .orElseThrow(() -> violation(Kind.NOT_FOUND, "图片项不存在或不可访问"));
        Map<String,Object> result = new LinkedHashMap<>(item(value));
        if ("READY".equals(value.status()) || "COMPLETED".equals(value.status())) {
            var url = storage.authorizeRead(value.bucket(), value.objectKey(), properties.readTtl());
            result.put("read", Map.of("url", url.toString(), "expires_at",
                Instant.now(clock).plus(properties.readTtl()).toString()));
        }
        return result;
    }

    public Map<String,Object> list(UUID actor, boolean all, String cursor) {
        Instant before = null; UUID beforeId = null;
        if (cursor != null && !cursor.isBlank()) {
            try {
                String[] parts = cursor.split("\\|", -1);
                before = Instant.parse(parts[0]); beforeId = UUID.fromString(parts[1]);
            } catch (RuntimeException invalid) {
                throw violation(Kind.INTEGRITY, "游标不合法");
            }
        }
        var page = repository.list(actor, all, before, beforeId, 50);
        Map<String,Object> result = new LinkedHashMap<>();
        result.put("items", page.items().stream().map(ManualDetectionBatchService::batch).toList());
        if (page.nextCursor() != null) result.put("next_cursor", page.nextCursor());
        return result;
    }

    public int cleanupExpired() {
        var orphans = repository.claimExpiredOrphans(
            Instant.now(clock).minus(properties.orphanRetention()), properties.cleanupBatchSize());
        int resolved = 0;
        for (var orphan : orphans) {
            try {
                storage.delete(orphan.bucket(), orphan.objectKey());
                repository.recordOrphanCleanup(orphan, true, "TD-STORAGE-ORPHAN-CLEANUP-RESOLVED");
                resolved++;
            } catch (RuntimeException failure) {
                repository.recordOrphanCleanup(orphan, false, "TD-STORAGE-ORPHAN-CLEANUP-HOLD");
            }
        }
        return resolved;
    }

    private String propertiesObjectBucket() {
        return properties.objectBucket();
    }

    private void requireEnabled() {
        if (!properties.enabled()) throw violation(Kind.DISABLED, "手工检测功能未启用");
    }

    private void audit(UUID actor, String action, UUID resource, String before, String after,
            String requestId, String traceId) {
        audit.append(new AuditRecord(UUID.randomUUID(), Instant.now(clock), "USER", actor.toString(),
            action, "DETECTION_BATCH", resource.toString(), before, after, null,
            requestId, traceId, "SUCCESS", null));
    }

    private static String digest(Object value) { return value == null ? null : CanonicalJson.sha256(value); }
    private static ManualDetectionViolation violation(Kind kind,String message){return new ManualDetectionViolation(kind,message);}

    private static Map<String,Object> batch(ManualDetectionRepository.BatchView value) {
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("batch_id",value.batchId()); map.put("batch_no",value.batchNo());
        map.put("source","MANUAL_UPLOAD"); map.put("created_by",value.createdBy());
        map.put("usage_stage",value.usageStage()); if(value.usageStageNote()!=null)map.put("usage_stage_note",value.usageStageNote());
        map.put("status",value.status()); var c=value.counts();
        map.put("counts",Map.of("total",c.total(),"completed",c.completed(),"defect_suspected",c.defectSuspected(),
            "normal",c.normal(),"inconclusive",c.inconclusive(),"quality_rejected",c.qualityRejected(),"technical_failed",c.technicalFailed()));
        map.put("created_at",value.createdAt());map.put("updated_at",value.updatedAt());map.put("version",value.version());return map;
    }

    private static Map<String,Object> item(ManualDetectionRepository.ItemView value) {
        Map<String,Object> image=new LinkedHashMap<>(); image.put("bucket",value.bucket());image.put("object_key",value.objectKey());
        image.put("sha256",value.sha256());image.put("size_bytes",value.sizeBytes());image.put("media_type",value.mediaType());
        if(value.objectVersion()!=null&&!value.objectVersion().isBlank())image.put("object_version",value.objectVersion());
        Map<String,Object> map=new LinkedHashMap<>();map.put("batch_item_id",value.itemId());map.put("batch_id",value.batchId());
        map.put("image",image);map.put("status",value.status());if(value.algorithmOutcome()!=null)map.put("algorithm_outcome",value.algorithmOutcome());
        if(value.quickReviewDecision()!=null)map.put("quick_review_decision",value.quickReviewDecision());map.put("created_at",value.createdAt());map.put("updated_at",value.updatedAt());return map;
    }
}
