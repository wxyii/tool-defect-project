package com.tooldefect.business.detectionbatch.application;

import java.time.Clock;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.nio.charset.StandardCharsets;

import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.audit.domain.AuditRecord;
import com.tooldefect.business.detectionbatch.application.ManualDetectionViolation.Kind;
import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.OutboxRepository;
import com.tooldefect.business.shared.messaging.OutboxEvent;
import com.tooldefect.business.storage.application.ObjectStoragePort;

public class ManualDetectionBatchService {
    private static final Set<String> STAGES = Set.of("NEW_BLADE", "AFTER_ONE_WHEEL",
        "AFTER_TWO_WHEELS", "AFTER_THREE_WHEELS", "OTHER", "UNSPECIFIED");
    private static final Set<String> QUICK_REVIEW_DECISIONS = Set.of(
        "DEFECT_CONFIRMED", "NO_DEFECT_CONFIRMED", "UNABLE_TO_DETERMINE");
    private final ManualDetectionRepository repository;
    private final ObjectStoragePort storage;
    private final IdempotencyService idempotency;
    private final AuditTrail audit;
    private final ManualDetectionSettings properties;
    private final Clock clock;
    private final OutboxRepository outbox;

    public ManualDetectionBatchService(ManualDetectionRepository repository,
            ObjectStoragePort storage, IdempotencyService idempotency, AuditTrail audit,
            ManualDetectionSettings properties, Clock clock) {
        this(repository, storage, idempotency, audit, properties, clock, null);
    }

    public ManualDetectionBatchService(ManualDetectionRepository repository,
            ObjectStoragePort storage, IdempotencyService idempotency, AuditTrail audit,
            ManualDetectionSettings properties, Clock clock, OutboxRepository outbox) {
        this.repository = java.util.Objects.requireNonNull(repository);
        this.storage = java.util.Objects.requireNonNull(storage);
        this.idempotency = java.util.Objects.requireNonNull(idempotency);
        this.audit = java.util.Objects.requireNonNull(audit);
        this.properties = java.util.Objects.requireNonNull(properties);
        this.clock = java.util.Objects.requireNonNull(clock);
        this.outbox = outbox;
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
            audit(actor, "MANUAL_BATCH_CREATE", batch.batchId(), null, digestBatch(batch), requestId, traceId);
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
            audit(actor, "MANUAL_BATCH_ITEM_ADD", batchId, null, digestItem(intent.item()), requestId, traceId);
            return new IdempotencyService.Response(201, body);
        });
    }

    @Transactional
    public IdempotencyService.Response renewUpload(UUID actor, UUID batchId, UUID itemId,
            String key, Map<String,Object> request, String requestId, String traceId) {
        requireEnabled();
        return idempotency.execute("v2.manual-batch.renew-upload:" + itemId,
            actor.toString(), key, request, () -> {
                var current = repository.findUpload(batchId, itemId, actor)
                    .orElseThrow(() -> violation(Kind.NOT_FOUND, "图片项不存在"));
                if (!"UPLOADING".equals(current.item().status())) {
                    throw violation(Kind.CONFLICT, "图片项不处于可续签上传状态");
                }
                var ticket = storage.authorizeUpload(current.item().bucket(),
                    current.item().objectKey(), current.expectedSizeBytes(),
                    current.expectedSha256(), current.expectedMediaType(),
                    Map.of("batch-id", batchId.toString(),
                        "batch-item-id", itemId.toString()), properties.uploadTtl());
                var renewed = repository.renewUpload(batchId, itemId, actor, ticket.expiresAt());
                Map<String,Object> body = new LinkedHashMap<>(item(renewed.item()));
                body.put("upload", Map.of("method", ticket.method(),
                    "url", ticket.url().toString(), "headers", ticket.headers(),
                    "expires_at", ticket.expiresAt().toString()));
                audit(actor, "MANUAL_BATCH_ITEM_UPLOAD_RENEW", batchId, null,
                    digestItem(renewed.item()), requestId, traceId);
                return new IdempotencyService.Response(200, body);
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
            audit(actor, "MANUAL_BATCH_ITEM_CONFIRM", batchId, null, digestItem(confirmed), requestId, traceId);
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
            for (var task : repository.queuedTasks(batchId, key)) {
                appendSingleItemTask(task, key, traceId);
            }
            audit(actor, "MANUAL_BATCH_SUBMIT", batchId, digestBatch(before), digestBatch(after), requestId, traceId);
            return new IdempotencyService.Response(202, batch(after));
        });
    }

    private void appendSingleItemTask(ManualDetectionRepository.TaskDispatch task,
            String key, String traceId) {
        if (outbox == null) {
            throw violation(Kind.DISABLED, "第二版推理发件箱未配置");
        }
        UUID messageId = UUID.nameUUIDFromBytes(
            ("r4-message:" + task.detectionTaskId()).getBytes(StandardCharsets.UTF_8));
        UUID eventId = UUID.nameUUIDFromBytes(
            ("r4-outbox:" + task.detectionTaskId()).getBytes(StandardCharsets.UTF_8));
        Instant occurredAt = Instant.now(clock);
        String traceparent = "00-" + traceId + "-"
            + CanonicalJson.sha256(messageId.toString()).substring(0, 16) + "-01";
        Map<String,Object> image = new LinkedHashMap<>();
        image.put("bucket", task.bucket()); image.put("object_key", task.objectKey());
        image.put("sha256", task.sha256()); image.put("size_bytes", task.sizeBytes());
        image.put("media_type", task.mediaType());
        if (task.objectVersion() != null && !task.objectVersion().isBlank()) {
            image.put("object_version", task.objectVersion());
        }
        Map<String,Object> payload = new LinkedHashMap<>();
        payload.put("message_id", messageId.toString());
        payload.put("occurred_at", occurredAt.toString());
        payload.put("idempotency_key", key);
        payload.put("traceparent", traceparent);
        payload.put("batch_item_id", task.batchItemId().toString());
        payload.put("detection_task_id", task.detectionTaskId().toString());
        payload.put("image", image);
        payload.put("pipeline_version", "2.0.0");
        outbox.append(OutboxEvent.pending(eventId, "detection_task",
            task.detectionTaskId(), "tool_defect.inference.item.requested.v2",
            "inference.item.requested.v2", CanonicalJson.encode(payload), occurredAt));
    }

    public Map<String,Object> getBatch(UUID actor, boolean all, UUID batchId) {
        var result = new LinkedHashMap<>(batch(repository.findBatch(batchId, actor, all)
            .orElseThrow(() -> violation(Kind.NOT_FOUND, "批次不存在或不可访问"))));
        result.put("items", repository.listItems(batchId, actor, all).stream()
            .map(ManualDetectionBatchService::item).toList());
        return result;
    }

    public Map<String,Object> getItem(UUID actor, boolean all, UUID batchId, UUID itemId) {
        var value = repository.findItem(batchId, itemId, actor, all)
            .orElseThrow(() -> violation(Kind.NOT_FOUND, "图片项不存在或不可访问"));
        Map<String,Object> result = new LinkedHashMap<>(item(value));
        if (Set.of("READY", "QUEUED", "PROCESSING", "COMPLETED",
                "QUALITY_REJECTED", "FAILED").contains(value.status())) {
            var url = storage.authorizeRead(value.bucket(), value.objectKey(), properties.readTtl());
            result.put("read", Map.of("url", url.toString(), "expires_at",
                Instant.now(clock).plus(properties.readTtl()).toString()));
        }
        var evidence = repository.findItemEvidence(itemId);
        if (evidence.quality() != null) {
            result.put("quality", quality(evidence.quality()));
        }
        if (evidence.result() != null) {
            var execution = evidence.result();
            Map<String,Object> executionMap = new LinkedHashMap<>();
            executionMap.put("attempt_id", execution.attemptId());
            executionMap.put("created_at", execution.createdAt());
            if (execution.errorCode() != null) {
                executionMap.put("error_code", execution.errorCode());
                executionMap.put("retryable", execution.retryable());
            } else {
                Map<String,Object> reference = new LinkedHashMap<>();
                reference.put("bucket", execution.bucket());
                reference.put("object_key", execution.objectKey());
                reference.put("sha256", execution.sha256());
                reference.put("size_bytes", execution.sizeBytes());
                reference.put("media_type", "application/json");
                if (execution.objectVersion() != null) {
                    reference.put("object_version", execution.objectVersion());
                }
                executionMap.put("result_reference", reference);
                var resultUrl = storage.authorizeRead(execution.bucket(),
                    execution.objectKey(), properties.readTtl());
                executionMap.put("result_read", Map.of("url", resultUrl.toString(),
                    "expires_at", Instant.now(clock).plus(properties.readTtl()).toString()));
            }
            result.put("execution", executionMap);
        }
        return result;
    }

    @Transactional
    public IdempotencyService.Response saveQuickReview(UUID actor, boolean all,
            UUID batchId, UUID itemId, String key, String decision, UUID supersedesId,
            Map<String,Object> request, String requestId, String traceId) {
        requireEnabled();
        if (!QUICK_REVIEW_DECISIONS.contains(decision)) {
            throw violation(Kind.INTEGRITY, "快速反馈结论不合法");
        }
        return idempotency.execute("v2.quick-review:" + itemId, actor.toString(), key,
            request, () -> {
                var record = repository.saveQuickReview(batchId, itemId, actor, all,
                    decision, supersedesId, key);
                audit(actor, "QUICK_REVIEW_SUBMIT", batchId, null, digestQuickReview(record),
                    requestId, traceId);
                return new IdempotencyService.Response(200, quickReview(record));
            });
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

    private static String digestBatch(ManualDetectionRepository.BatchView value) {
        return CanonicalJson.sha256(batchSnapshot(value));
    }

    private static String digestItem(ManualDetectionRepository.ItemView value) {
        return CanonicalJson.sha256(itemSnapshot(value));
    }

    private static String digestQuickReview(ManualDetectionRepository.QuickReviewView value) {
        return CanonicalJson.sha256(quickReviewSnapshot(value));
    }

    private static Map<String,Object> batchSnapshot(ManualDetectionRepository.BatchView value) {
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("batch_id", value.batchId().toString());
        map.put("batch_no", value.batchNo());
        map.put("source", "MANUAL_UPLOAD");
        map.put("created_by", value.createdBy().toString());
        map.put("usage_stage", value.usageStage());
        if (value.usageStageNote() != null) map.put("usage_stage_note", value.usageStageNote());
        map.put("status", value.status());
        map.put("counts", countsSnapshot(value.counts()));
        map.put("created_at", value.createdAt().toString());
        map.put("updated_at", value.updatedAt().toString());
        map.put("version", value.version());
        return map;
    }

    private static Map<String,Object> countsSnapshot(ManualDetectionRepository.Counts value) {
        return Map.of(
            "total", value.total(),
            "completed", value.completed(),
            "defect_suspected", value.defectSuspected(),
            "normal", value.normal(),
            "inconclusive", value.inconclusive(),
            "quality_rejected", value.qualityRejected(),
            "technical_failed", value.technicalFailed()
        );
    }

    private static Map<String,Object> itemSnapshot(ManualDetectionRepository.ItemView value) {
        Map<String,Object> image = new LinkedHashMap<>();
        image.put("bucket", value.bucket());
        image.put("object_key", value.objectKey());
        image.put("sha256", value.sha256());
        image.put("size_bytes", value.sizeBytes());
        image.put("media_type", value.mediaType());
        if (value.objectVersion() != null && !value.objectVersion().isBlank()) {
            image.put("object_version", value.objectVersion());
        }
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("batch_item_id", value.itemId().toString());
        map.put("batch_id", value.batchId().toString());
        map.put("image", image);
        map.put("status", value.status());
        if (value.algorithmOutcome() != null) map.put("algorithm_outcome", value.algorithmOutcome());
        if (value.quickReviewDecision() != null) map.put("quick_review_decision", value.quickReviewDecision());
        map.put("created_at", value.createdAt().toString());
        map.put("updated_at", value.updatedAt().toString());
        return map;
    }

    private static Map<String,Object> quickReviewSnapshot(
            ManualDetectionRepository.QuickReviewView value) {
        Map<String,Object> map = new LinkedHashMap<>();
        map.put("review_record_id", value.reviewRecordId().toString());
        map.put("batch_item_id", value.batchItemId().toString());
        map.put("decision", value.decision());
        map.put("submitted_by", value.submittedBy().toString());
        map.put("submitted_at", value.submittedAt().toString());
        map.put("idempotency_key", value.idempotencyKey());
        if (value.supersedesRecordId() != null) {
            map.put("supersedes_record_id", value.supersedesRecordId().toString());
        }
        return map;
    }

    private static ManualDetectionViolation violation(Kind kind,String message){return new ManualDetectionViolation(kind,message);}

    private static Map<String,Object> batch(ManualDetectionRepository.BatchView value) {
        return batchSnapshot(value);
    }

    private static Map<String,Object> item(ManualDetectionRepository.ItemView value) {
        return itemSnapshot(value);
    }

    private static Map<String,Object> quickReview(
            ManualDetectionRepository.QuickReviewView value) {
        return quickReviewSnapshot(value);
    }

    private static Map<String,Object> quality(ManualDetectionRepository.QualityView value) {
        Map<String,Object> result = new LinkedHashMap<>();
        result.put("overall", value.overall());
        result.put("checker_version", value.checkerVersion());
        result.put("checks", value.checks().stream().map(check -> {
            Map<String,Object> mapped = new LinkedHashMap<>();
            mapped.put("check_type", check.checkType()); mapped.put("status", check.status());
            mapped.put("rule_id", check.ruleId()); mapped.put("reason_code", check.reasonCode());
            mapped.put("user_hint", check.userHint());
            if (check.measurement() != null) mapped.put("measurement", check.measurement());
            if (check.threshold() != null) mapped.put("threshold", check.threshold());
            return mapped;
        }).toList());
        return result;
    }
}
