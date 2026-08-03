package com.tooldefect.business.detectionbatch.application;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.OutboxRepository;
import com.tooldefect.business.shared.messaging.OutboxEvent;
import com.tooldefect.business.storage.application.ObjectStoragePort;

public class ProductionDetectionService {
    private final ProductionDetectionRepository repository;
    private final ObjectStoragePort storage;
    private final IdempotencyService idempotency;
    private final OutboxRepository outbox;
    private final Clock clock;

    public ProductionDetectionService(ProductionDetectionRepository repository,
            ObjectStoragePort storage, IdempotencyService idempotency,
            OutboxRepository outbox, Clock clock) {
        this.repository = java.util.Objects.requireNonNull(repository);
        this.storage = java.util.Objects.requireNonNull(storage);
        this.idempotency = java.util.Objects.requireNonNull(idempotency);
        this.outbox = java.util.Objects.requireNonNull(outbox);
        this.clock = java.util.Objects.requireNonNull(clock);
    }

    @Transactional
    public IdempotencyService.Response create(UUID captureId, String deviceSubject,
            ProductionDetectionRepository.Image image, String key,
            Map<String,Object> request, String traceparent) {
        if (!image.objectKey().startsWith("production-originals/")
                || !image.sha256().matches("[0-9a-f]{64}")
                || image.sizeBytes() < 1
                || !java.util.Set.of("image/jpeg", "image/png").contains(image.mediaType())) {
            throw new ManualDetectionViolation(
                ManualDetectionViolation.Kind.INTEGRITY, "产线单图对象引用不合法");
        }
        return idempotency.execute("v2.production-item", deviceSubject, key, request, () -> {
            var head = storage.head(image.bucket(), image.objectKey());
            if (!image.sha256().equals(head.sha256())
                    || image.sizeBytes() != head.sizeBytes()
                    || !image.mediaType().equalsIgnoreCase(head.mediaType())
                    || image.objectVersion() != null
                        && !image.objectVersion().equals(head.objectVersion())) {
                throw new ManualDetectionViolation(
                    ManualDetectionViolation.Kind.INTEGRITY,
                    "产线对象头、版本、大小、类型或哈希冲突");
            }
            var normalized = new ProductionDetectionRepository.Image(
                image.bucket(), image.objectKey(), head.objectVersion(), image.sha256(),
                image.sizeBytes(), image.mediaType(), head.width(), head.height());
            if (normalized.width() < 1 || normalized.height() < 1) {
                throw new ManualDetectionViolation(
                    ManualDetectionViolation.Kind.INTEGRITY,
                    "产线对象解码宽高无效");
            }
            var acceptance = repository.create(
                captureId, deviceSubject, normalized, key);
            appendTask(acceptance, key, traceparent);
            return new IdempotencyService.Response(202, Map.of(
                "capture_id", acceptance.captureId(),
                "batch_id", acceptance.batchId(),
                "batch_item_id", acceptance.batchItemId(),
                "detection_task_id", acceptance.detectionTaskId(),
                "status", acceptance.status()));
        });
    }

    private void appendTask(ProductionDetectionRepository.Acceptance value,
            String key, String traceparent) {
        UUID messageId = UUID.nameUUIDFromBytes(
            ("r4-message:" + value.detectionTaskId()).getBytes(StandardCharsets.UTF_8));
        UUID eventId = UUID.nameUUIDFromBytes(
            ("r4-outbox:" + value.detectionTaskId()).getBytes(StandardCharsets.UTF_8));
        Instant occurredAt = Instant.now(clock);
        var source = value.image();
        Map<String,Object> image = new LinkedHashMap<>();
        image.put("bucket", source.bucket()); image.put("object_key", source.objectKey());
        image.put("sha256", source.sha256()); image.put("size_bytes", source.sizeBytes());
        image.put("media_type", source.mediaType());
        if (source.objectVersion() != null && !source.objectVersion().isBlank()) {
            image.put("object_version", source.objectVersion());
        }
        Map<String,Object> payload = new LinkedHashMap<>();
        payload.put("message_id", messageId.toString()); payload.put("occurred_at", occurredAt.toString());
        payload.put("idempotency_key", key); payload.put("traceparent", traceparent);
        payload.put("batch_item_id", value.batchItemId().toString());
        payload.put("detection_task_id", value.detectionTaskId().toString());
        payload.put("image", image); payload.put("pipeline_version", "2.0.0");
        outbox.append(OutboxEvent.pending(eventId, "detection_task", value.detectionTaskId(),
            "tool_defect.inference.item.requested.v2", "inference.item.requested.v2",
            CanonicalJson.encode(payload), occurredAt));
    }
}
