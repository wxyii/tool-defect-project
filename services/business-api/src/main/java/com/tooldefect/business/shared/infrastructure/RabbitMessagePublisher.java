package com.tooldefect.business.shared.infrastructure;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.HashSet;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.TimeUnit;

import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

import com.tooldefect.business.shared.application.MessagePublisher;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.messaging.OutboxEvent;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

public final class RabbitMessagePublisher implements MessagePublisher {
    private static final String OUTBOX_EVENT_TYPE =
        "tool_defect.outbox.inference_requested.v1";
    private static final String INFERENCE_TASK_EVENT_TYPE =
        "tool_defect.inference.task.v1";
    private static final Set<String> OUTBOX_FIELDS = Set.of(
        "event_id",
        "event_type",
        "aggregate_type",
        "aggregate_id",
        "occurred_at",
        "message_id",
        "traceparent",
        "payload"
    );
    private static final Set<String> TASK_FIELDS = Set.of(
        "event_type",
        "message_id",
        "occurred_at",
        "traceparent",
        "detection_task_id",
        "capture_id",
        "pipeline",
        "images",
        "deadline_at"
    );
    private static final Set<String> PIPELINE_FIELDS = Set.of(
        "pipeline_id",
        "version",
        "config_sha256",
        "preprocessor_version",
        "algorithm_version",
        "model_version"
    );
    private static final Set<String> IMAGE_REQUIRED_FIELDS = Set.of(
        "image_id", "kind", "object", "width", "height"
    );
    private static final Set<String> IMAGE_FIELDS = Set.of(
        "image_id", "kind", "object", "width", "height", "image_role"
    );
    private static final Set<String> OBJECT_REQUIRED_FIELDS = Set.of(
        "bucket", "object_key", "sha256", "size_bytes", "media_type"
    );
    private static final Set<String> OBJECT_FIELDS = Set.of(
        "bucket",
        "object_key",
        "object_version",
        "sha256",
        "size_bytes",
        "media_type"
    );
    private static final Set<String> IMAGE_KINDS = Set.of(
        "RAW",
        "THUMBNAIL",
        "DEFECT_MASK",
        "HEATMAP",
        "OVERLAY",
        "POLAR",
        "REVIEW_MASK"
    );
    private static final Set<String> OBJECT_MEDIA_TYPES = Set.of(
        "image/png",
        "image/jpeg",
        "application/json",
        "application/octet-stream"
    );
    private final RabbitTemplate rabbit;
    private final Duration confirmTimeout;
    private final ObjectMapper json;

    public RabbitMessagePublisher(
            RabbitTemplate rabbit,
            Duration confirmTimeout,
            ObjectMapper json) {
        this.rabbit = Objects.requireNonNull(rabbit);
        this.json = Objects.requireNonNull(json);
        if (confirmTimeout == null
                || confirmTimeout.isZero()
                || confirmTimeout.isNegative()) {
            throw new DomainViolation("发布确认超时必须大于 0");
        }
        this.confirmTimeout = confirmTimeout;
    }

    @Override
    public void publishAndConfirm(OutboxEvent event) {
        MessageIdentity identity = messageIdentity(event);
        CorrelationData correlation = new CorrelationData(event.eventId().toString());
        var builder = MessageBuilder
            .withBody(identity.payloadJson().getBytes(StandardCharsets.UTF_8))
            .setContentType("application/json")
            .setContentEncoding(StandardCharsets.UTF_8.name())
            .setDeliveryMode(MessageDeliveryMode.PERSISTENT)
            .setMessageId(identity.messageId())
            .setType(identity.eventType())
            .setHeader("schema_version", "1.0");
        if (identity.traceparent() != null) {
            builder.setHeader("traceparent", identity.traceparent());
        }
        Message message = builder.build();
        try {
            rabbit.send(
                RabbitTopology.EXCHANGE,
                event.routingKey(),
                message,
                correlation
            );
            CorrelationData.Confirm confirm = correlation.getFuture().get(
                confirmTimeout.toMillis(),
                TimeUnit.MILLISECONDS
            );
            if (!confirm.ack()) {
                throw new DomainViolation(
                    "RabbitMQ 拒绝发布：" + Objects.toString(confirm.reason(), "无原因")
                );
            }
            if (correlation.getReturned() != null) {
                throw new DomainViolation(
                    "RabbitMQ mandatory 发布不可路由："
                        + correlation.getReturned().getReplyText()
                );
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new DomainViolation("等待 RabbitMQ 发布确认时被中断", interrupted);
        } catch (java.util.concurrent.TimeoutException timeout) {
            throw new DomainViolation("等待 RabbitMQ 发布确认超时", timeout);
        } catch (java.util.concurrent.ExecutionException failed) {
            throw new DomainViolation("RabbitMQ 发布确认失败", failed);
        }
    }

    private MessageIdentity messageIdentity(OutboxEvent event) {
        try {
            JsonNode envelope = json.readTree(event.payloadJson());
            requireObjectFields(
                envelope,
                OUTBOX_FIELDS,
                OUTBOX_FIELDS,
                "发件箱事件"
            );
            java.util.UUID envelopeEventId = java.util.UUID.fromString(
                requiredText(envelope, "event_id")
            );
            String envelopeEventType = requiredText(envelope, "event_type");
            String aggregateType = requiredText(envelope, "aggregate_type");
            java.util.UUID aggregateId = java.util.UUID.fromString(
                requiredText(envelope, "aggregate_id")
            );
            String envelopeMessageId = requiredText(envelope, "message_id");
            java.util.UUID.fromString(envelopeMessageId);
            Instant envelopeOccurredAt = requiredUtcInstant(
                envelope,
                "occurred_at"
            );
            String envelopeTraceparent = requiredTraceparent(
                envelope,
                "traceparent"
            );
            if (!event.eventId().equals(envelopeEventId)
                    || !OUTBOX_EVENT_TYPE.equals(event.eventType())
                    || !OUTBOX_EVENT_TYPE.equals(envelopeEventType)) {
                throw new DomainViolation("发件箱信封标识或事件类型与记录不一致");
            }
            if (!"detection_task".equals(event.aggregateType())
                    || !event.aggregateType().equals(aggregateType)
                    || !event.aggregateId().equals(aggregateId)) {
                throw new DomainViolation("发件箱信封聚合与记录不一致");
            }
            if (Duration.between(event.createdAt(), envelopeOccurredAt)
                    .abs()
                    .compareTo(Duration.ofMillis(1)) > 0) {
                throw new DomainViolation("发件箱信封事件时间与记录不一致");
            }

            JsonNode task = envelope.path("payload");
            requireObjectFields(task, TASK_FIELDS, TASK_FIELDS, "推理任务");
            String messageId = requiredText(task, "message_id");
            String eventType = requiredText(task, "event_type");
            String detectionTaskId = requiredText(task, "detection_task_id");
            java.util.UUID.fromString(messageId);
            java.util.UUID taskId = java.util.UUID.fromString(detectionTaskId);
            java.util.UUID.fromString(requiredText(task, "capture_id"));
            if (!taskId.equals(event.aggregateId())) {
                throw new DomainViolation("消息 detection_task_id 与聚合标识不一致");
            }
            if (!INFERENCE_TASK_EVENT_TYPE.equals(eventType)
                    || !messageId.equals(envelopeMessageId)) {
                throw new DomainViolation("推理任务类型或 message_id 与信封不一致");
            }
            Instant occurredAt = requiredUtcInstant(task, "occurred_at");
            Instant deadlineAt = requiredUtcInstant(task, "deadline_at");
            if (!deadlineAt.isAfter(occurredAt)) {
                throw new DomainViolation("推理任务截止时间必须晚于事件时间");
            }
            String traceparent = requiredTraceparent(task, "traceparent");
            if (!occurredAt.equals(envelopeOccurredAt)
                    || !traceparent.equals(envelopeTraceparent)) {
                throw new DomainViolation("推理任务时间或追踪上下文与信封不一致");
            }
            validatePipeline(task.path("pipeline"));
            validateImages(task.path("images"));
            return new MessageIdentity(
                messageId,
                eventType,
                detectionTaskId,
                traceparent,
                json.writeValueAsString(task)
            );
        } catch (tools.jackson.core.JacksonException | IllegalArgumentException error) {
            throw new DomainViolation("发件箱 payload 不符合推理事件 v1", error);
        }
    }

    private static String requiredText(JsonNode root, String field) {
        JsonNode node = root.path(field);
        if (!node.isString()) {
            throw new DomainViolation("消息字段必须是字符串：" + field);
        }
        String value = node.stringValue();
        if (value.isBlank()) {
            throw new DomainViolation("消息缺少字段：" + field);
        }
        return value;
    }

    private static Instant requiredUtcInstant(JsonNode root, String field) {
        String value = requiredText(root, field);
        if (!value.endsWith("Z")) {
            throw new DomainViolation(field + " 必须是 UTC 时间");
        }
        return Instant.parse(value);
    }

    private static String requiredTraceparent(JsonNode root, String field) {
        String value = requiredText(root, field);
        if (!value.matches(
                "^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$")) {
            throw new DomainViolation(field + " 不符合 v1 契约");
        }
        return value;
    }

    private static void validatePipeline(JsonNode pipeline) {
        requireObjectFields(
            pipeline,
            PIPELINE_FIELDS,
            PIPELINE_FIELDS,
            "pipeline"
        );
        requireUuid(pipeline, "pipeline_id");
        requireVersion(pipeline, "version");
        requireSha256(pipeline, "config_sha256");
        requireVersion(pipeline, "preprocessor_version");
        requireVersion(pipeline, "algorithm_version");
        requireVersion(pipeline, "model_version");
    }

    private static void validateImages(JsonNode images) {
        if (!images.isArray() || images.isEmpty() || images.size() > 16) {
            throw new DomainViolation("images 数量不符合 v1 契约");
        }
        for (JsonNode image : images) {
            requireObjectFields(
                image,
                IMAGE_REQUIRED_FIELDS,
                IMAGE_FIELDS,
                "image"
            );
            requireUuid(image, "image_id");
            if (!IMAGE_KINDS.contains(requiredText(image, "kind"))) {
                throw new DomainViolation("image.kind 不符合 v1 契约");
            }
            requirePositiveInteger(image, "width", 32_768);
            requirePositiveInteger(image, "height", 32_768);
            JsonNode imageRole = image.path("image_role");
            if (!imageRole.isMissingNode()) {
                if (!imageRole.isString()) {
                    throw new DomainViolation("image_role 不符合 v1 契约");
                }
                String role = imageRole.stringValue();
                if (role.isBlank() || role.length() > 64) {
                    throw new DomainViolation("image_role 不符合 v1 契约");
                }
            }
            validateObjectReference(image.path("object"));
        }
    }

    private static void validateObjectReference(JsonNode object) {
        requireObjectFields(
            object,
            OBJECT_REQUIRED_FIELDS,
            OBJECT_FIELDS,
            "object"
        );
        String bucket = requiredText(object, "bucket");
        if (bucket.length() > 128
                || !bucket.matches("^[a-z0-9][a-z0-9.-]*$")) {
            throw new DomainViolation("object.bucket 不符合 v1 契约");
        }
        String key = requiredText(object, "object_key");
        if (key.length() > 1_024
                || !key.matches(
                    "^(?!/)(?![A-Za-z]:)(?!https?://)[A-Za-z0-9][A-Za-z0-9._/-]*$")) {
            throw new DomainViolation("object.object_key 不符合 v1 契约");
        }
        JsonNode objectVersion = object.path("object_version");
        if (!objectVersion.isMissingNode() && !objectVersion.isNull()) {
            if (!objectVersion.isString()) {
                throw new DomainViolation("object.object_version 不符合 v1 契约");
            }
            String value = objectVersion.stringValue();
            if (value.length() > 256) {
                throw new DomainViolation("object.object_version 不符合 v1 契约");
            }
        }
        requireSha256(object, "sha256");
        requirePositiveInteger(object, "size_bytes", Long.MAX_VALUE);
        if (!OBJECT_MEDIA_TYPES.contains(requiredText(object, "media_type"))) {
            throw new DomainViolation("object.media_type 不符合 v1 契约");
        }
    }

    private static void requireObjectFields(
            JsonNode value,
            Set<String> required,
            Set<String> allowed,
            String name) {
        if (!value.isObject()) {
            throw new DomainViolation(name + " 必须是对象");
        }
        Set<String> actual = new HashSet<>();
        value.properties().forEach(property -> actual.add(property.getKey()));
        if (!actual.containsAll(required) || !allowed.containsAll(actual)) {
            throw new DomainViolation(name + " 字段不符合 v1 契约");
        }
    }

    private static void requireUuid(JsonNode root, String field) {
        java.util.UUID.fromString(requiredText(root, field));
    }

    private static void requireSha256(JsonNode root, String field) {
        if (!requiredText(root, field).matches("^[a-f0-9]{64}$")) {
            throw new DomainViolation(field + " 不符合 v1 SHA-256");
        }
    }

    private static void requireVersion(JsonNode root, String field) {
        String value = requiredText(root, field);
        if (value.length() > 128
                || !value.matches("^[A-Za-z0-9][A-Za-z0-9._/-]*$")) {
            throw new DomainViolation(field + " 不符合 v1 版本格式");
        }
    }

    private static void requirePositiveInteger(
            JsonNode root,
            String field,
            long maximum) {
        JsonNode value = root.path(field);
        if (!value.isIntegralNumber()
                || value.longValue() < 1
                || value.longValue() > maximum) {
            throw new DomainViolation(field + " 必须是范围内的正整数");
        }
    }

    private record MessageIdentity(
        String messageId,
        String eventType,
        String detectionTaskId,
        String traceparent,
        String payloadJson
    ) {
    }
}
