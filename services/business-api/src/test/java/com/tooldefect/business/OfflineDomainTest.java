package com.tooldefect.business;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.OptionalDouble;
import java.util.UUID;

import com.tooldefect.business.detection.domain.AlgorithmOutcome;
import com.tooldefect.business.detection.domain.DetectionResult;
import com.tooldefect.business.shared.application.MessagePublisher;
import com.tooldefect.business.shared.application.NonRetryableMessageException;
import com.tooldefect.business.shared.application.OutboxRepository;
import com.tooldefect.business.shared.application.ReliableMessagingService;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.messaging.OutboxEvent;
import com.tooldefect.business.shared.messaging.OutboxStatus;
import com.tooldefect.business.storage.domain.ObjectState;
import com.tooldefect.business.storage.domain.StoredObject;
import com.tooldefect.business.storage.domain.UploadSession;
import com.tooldefect.business.storage.domain.UploadSessionStatus;

/**
 * 无 Maven 或容器时运行的纯领域验证；不会把它冒充 Spring、PostgreSQL、
 * RabbitMQ 或 S3 的集成门禁。
 */
public final class OfflineDomainTest {
    private OfflineDomainTest() {
    }

    public static void main(String[] args) {
        resultSeparatesAlgorithmFromBusiness();
        objectConfirmationIsSafeAndIdempotent();
        uploadReceiptExpiresAndMatchesExactly();
        outboxRetriesOnlyAfterPublisherConfirmation();
        System.out.println("business-api 纯领域检查：通过");
    }

    private static void resultSeparatesAlgorithmFromBusiness() {
        DetectionResult result = new DetectionResult(
            uuid(10),
            uuid(11),
            uuid(12),
            "1.0.0",
            AlgorithmOutcome.UNQUALIFIED,
            OptionalDouble.of(0.9),
            Map.of("QUALIFIED", 0.1, "UNQUALIFIED", 0.9),
            "a".repeat(64)
        );
        require(result.algorithmOutcome() == AlgorithmOutcome.UNQUALIFIED, "算法结论错误");
        expectViolation(() -> new DetectionResult(
            uuid(13),
            uuid(14),
            uuid(15),
            "1.0.0",
            AlgorithmOutcome.QUALIFIED,
            OptionalDouble.of(1.2),
            Map.of("QUALIFIED", 1.2, "UNQUALIFIED", -0.2),
            "a".repeat(64)
        ));
    }

    private static void objectConfirmationIsSafeAndIdempotent() {
        StoredObject object = object(uuid(20), uuid(21), uuid(22));
        object.confirm(10, "b".repeat(64), "image/png", 10, 10, "version-1");
        object.confirm(10, "b".repeat(64), "image/png", 10, 10, "version-1");
        require(object.state() == ObjectState.AVAILABLE, "对象应可用");
        require(object.recordVersion() == 1, "重复确认不得重复推进版本");
        expectViolation(() ->
            object.confirm(10, "c".repeat(64), "image/png", 10, 10, "version-2")
        );
    }

    private static void uploadReceiptExpiresAndMatchesExactly() {
        UploadSession session = new UploadSession(
            uuid(23),
            uuid(20),
            uuid(21),
            uuid(22),
            "c".repeat(64),
            10,
            "b".repeat(64),
            "image/png",
            UploadSessionStatus.ISSUED,
            Instant.parse("2026-07-29T01:05:00Z")
        );
        require(session.receiptMatches("c".repeat(64)), "回执摘要应匹配");
        require(!session.receiptMatches("d".repeat(64)), "不同回执摘要不得匹配");
        require(session.requestMatches(10, "b".repeat(64)), "上传登记应精确匹配");
        require(
            session.expiredAt(Instant.parse("2026-07-29T01:05:00Z")),
            "到期时刻必须拒绝"
        );
    }

    private static void outboxRetriesOnlyAfterPublisherConfirmation() {
        MutableClock clock = new MutableClock(Instant.EPOCH);
        MemoryOutbox outbox = new MemoryOutbox();
        int[] attempts = {0};
        MessagePublisher publisher = event -> {
            attempts[0]++;
            if (attempts[0] == 1) {
                throw new RuntimeException("模拟发布确认丢失");
            }
        };
        ReliableMessagingService service = new ReliableMessagingService(
            outbox,
            publisher,
            clock,
            "offline-test",
            Duration.ofSeconds(30)
        );
        UUID eventId = uuid(40);
        UUID taskId = uuid(41);
        Instant occurredAt = Instant.EPOCH;
        OutboxEvent event = OutboxEvent.pending(
            eventId,
            "detection_task",
            taskId,
            "tool_defect.outbox.inference_requested.v1",
            "production.gpu.multitask",
            validOutboxPayload(eventId, taskId, occurredAt),
            occurredAt
        );
        outbox.append(event);
        require(service.publishDue(10) == 0, "首次发布失败时不得标为已发布");
        clock.advance(Duration.ofSeconds(1));
        require(service.publishDue(10) == 1, "发布确认恢复后应补发成功");
        require(attempts[0] == 2, "故障恢复应至少一次投递");
        require(outbox.event(uuid(40)).status() == OutboxStatus.PUBLISHED,
            "只有发布者确认后才能完成");

        MessagePublisher poisonPublisher = ignored -> {
            throw new NonRetryableMessageException("模拟不可恢复契约错误");
        };
        ReliableMessagingService poisonService = new ReliableMessagingService(
            outbox,
            poisonPublisher,
            clock,
            "offline-poison-test",
            Duration.ofSeconds(30),
            3,
            Duration.ofSeconds(1),
            Duration.ofSeconds(10),
            0.0
        );
        UUID poisonEventId = uuid(48);
        outbox.append(OutboxEvent.pending(
            poisonEventId,
            "detection_task",
            uuid(49),
            "tool_defect.outbox.inference_requested.v1",
            "production.gpu.multitask",
            validOutboxPayload(poisonEventId, uuid(49), clock.instant()),
            clock.instant()
        ));
        require(poisonService.publishDue(10) == 0,
            "不可恢复发布错误不得报告成功");
        require(outbox.event(poisonEventId).status() == OutboxStatus.DEAD,
            "不可恢复发布错误必须直接进入终止态");

        int[] boundedAttempts = {0};
        MessagePublisher unavailablePublisher = ignored -> {
            boundedAttempts[0]++;
            throw new RuntimeException("模拟持续不可用");
        };
        ReliableMessagingService boundedService = new ReliableMessagingService(
            outbox,
            unavailablePublisher,
            clock,
            "offline-bounded-test",
            Duration.ofSeconds(30),
            2,
            Duration.ofSeconds(1),
            Duration.ofSeconds(10),
            0.0
        );
        UUID boundedEventId = uuid(50);
        UUID boundedTaskId = uuid(51);
        outbox.append(OutboxEvent.pending(
            boundedEventId,
            "detection_task",
            boundedTaskId,
            "tool_defect.outbox.inference_requested.v1",
            "production.gpu.multitask",
            validOutboxPayload(boundedEventId, boundedTaskId, clock.instant()),
            clock.instant()
        ));
        boundedService.publishDue(10);
        clock.advance(Duration.ofSeconds(1));
        boundedService.publishDue(10);
        clock.advance(Duration.ofHours(1));
        boundedService.publishDue(10);
        require(boundedAttempts[0] == 2, "发布重试必须严格受最大次数限制");
        require(outbox.event(boundedEventId).status() == OutboxStatus.DEAD,
            "达到上限后必须进入终止态，不能形成重试风暴");

        expectViolation(() -> OutboxEvent.pending(
            uuid(42),
            "capture",
            uuid(43),
            "tool_defect.bad.v1",
            "production.gpu.multitask",
            "{\"payload\":{\"" + '\\' + "u0062ase64\":\"forbidden\"}}",
            Instant.EPOCH
        ));
    }

    private static String validOutboxPayload(
            UUID eventId,
            UUID taskId,
            Instant occurredAt) {
        UUID messageId = uuid(44);
        String traceparent =
            "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01";
        return """
            {
              "event_id":"%s",
              "event_type":"tool_defect.outbox.inference_requested.v1",
              "aggregate_type":"detection_task",
              "aggregate_id":"%s",
              "occurred_at":"%s",
              "message_id":"%s",
              "traceparent":"%s",
              "payload":{
                "event_type":"tool_defect.inference.task.v1",
                "message_id":"%s",
                "occurred_at":"%s",
                "traceparent":"%s",
                "detection_task_id":"%s",
                "capture_id":"%s",
                "pipeline":{
                  "pipeline_id":"%s",
                  "version":"1",
                  "config_sha256":"%s",
                  "preprocessor_version":"1",
                  "algorithm_version":"1",
                  "model_version":"1"
                },
                "images":[{
                  "image_id":"%s",
                  "kind":"RAW",
                  "object":{
                    "bucket":"td-raw",
                    "object_key":"raw/offline/sample.png",
                    "sha256":"%s",
                    "size_bytes":128,
                    "media_type":"image/png"
                  },
                  "width":32,
                  "height":32,
                  "image_role":"PRIMARY"
                }],
                "deadline_at":"%s"
              }
            }
            """.formatted(
                eventId,
                taskId,
                occurredAt,
                messageId,
                traceparent,
                messageId,
                occurredAt,
                traceparent,
                taskId,
                uuid(45),
                uuid(46),
                "d".repeat(64),
                uuid(47),
                "e".repeat(64),
                occurredAt.plusSeconds(30)
            );
    }

    private static StoredObject object(
            UUID imageId,
            UUID captureId,
            UUID stationId) {
        return new StoredObject(
            imageId,
            captureId,
            stationId,
            "td-raw",
            "raw/2026/07/29/" + stationId + "/" + captureId
                + "/primary-bbbbbbbbbbbbbbbb.png",
            10,
            "b".repeat(64),
            "image/png"
        );
    }

    private static UUID uuid(long value) {
        return new UUID(0x0000000000007000L, 0x8000000000000000L | value);
    }

    private static void expectViolation(Runnable action) {
        try {
            action.run();
        } catch (DomainViolation expected) {
            return;
        }
        throw new AssertionError("预期领域约束拒绝");
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }

    private static final class MemoryOutbox implements OutboxRepository {
        private final Map<UUID, OutboxEvent> events = new LinkedHashMap<>();

        @Override
        public void append(OutboxEvent event) {
            if (events.putIfAbsent(event.eventId(), event) != null) {
                throw new DomainViolation("重复 eventId");
            }
        }

        @Override
        public List<OutboxEvent> claimBatch(
                Instant now,
                int limit,
                String claimOwner,
                Duration leaseDuration) {
            return events.values().stream()
                .filter(event ->
                    (event.status() == OutboxStatus.NEW
                        || event.status() == OutboxStatus.FAILED)
                        && !event.nextAttemptAt().isAfter(now)
                    || event.status() == OutboxStatus.CLAIMED
                        && !event.leaseUntil().isAfter(now))
                .limit(limit)
                .map(event -> replace(new OutboxEvent(
                    event.eventId(),
                    event.aggregateType(),
                    event.aggregateId(),
                    event.eventType(),
                    event.routingKey(),
                    event.payloadJson(),
                    OutboxStatus.CLAIMED,
                    event.attemptCount() + 1,
                    event.nextAttemptAt(),
                    event.createdAt(),
                    null,
                    claimOwner,
                    now.plus(leaseDuration),
                    null
                )))
                .toList();
        }

        @Override
        public boolean markPublished(
                UUID eventId,
                String claimOwner,
                Instant publishedAt) {
            OutboxEvent event = events.get(eventId);
            if (event == null
                    || event.status() != OutboxStatus.CLAIMED
                    || !claimOwner.equals(event.claimOwner())) {
                return false;
            }
            replace(copy(event, OutboxStatus.PUBLISHED, event.nextAttemptAt(),
                publishedAt, null, null, null));
            return true;
        }

        @Override
        public boolean markFailed(
                UUID eventId,
                String claimOwner,
                Instant retryAt,
                String errorSummary) {
            OutboxEvent event = events.get(eventId);
            if (event == null
                    || event.status() != OutboxStatus.CLAIMED
                    || !claimOwner.equals(event.claimOwner())) {
                return false;
            }
            replace(copy(event, OutboxStatus.FAILED, retryAt,
                null, null, null, errorSummary));
            return true;
        }

        @Override
        public boolean markDead(
                UUID eventId,
                String claimOwner,
                Instant failedAt,
                String errorSummary) {
            OutboxEvent event = events.get(eventId);
            if (event == null
                    || event.status() != OutboxStatus.CLAIMED
                    || !claimOwner.equals(event.claimOwner())) {
                return false;
            }
            replace(copy(event, OutboxStatus.DEAD, failedAt,
                null, null, null, errorSummary));
            return true;
        }

        @Override
        public boolean exists(UUID eventId) {
            return events.containsKey(eventId);
        }

        OutboxEvent event(UUID eventId) {
            return events.get(eventId);
        }

        private OutboxEvent replace(OutboxEvent event) {
            events.put(event.eventId(), event);
            return event;
        }

        private static OutboxEvent copy(
                OutboxEvent event,
                OutboxStatus status,
                Instant retryAt,
                Instant publishedAt,
                String claimOwner,
                Instant leaseUntil,
                String error) {
            return new OutboxEvent(
                event.eventId(),
                event.aggregateType(),
                event.aggregateId(),
                event.eventType(),
                event.routingKey(),
                event.payloadJson(),
                status,
                event.attemptCount(),
                retryAt,
                event.createdAt(),
                publishedAt,
                claimOwner,
                leaseUntil,
                error
            );
        }
    }

    private static final class MutableClock extends Clock {
        private Instant value;

        MutableClock(Instant value) {
            this.value = value;
        }

        void advance(Duration duration) {
            value = value.plus(duration);
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return value;
        }
    }
}
