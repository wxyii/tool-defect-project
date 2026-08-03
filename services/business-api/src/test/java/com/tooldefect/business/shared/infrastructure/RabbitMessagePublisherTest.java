package com.tooldefect.business.shared.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Duration;
import java.time.Instant;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

import com.tooldefect.business.shared.application.NonRetryableMessageException;
import com.tooldefect.business.shared.messaging.OutboxEvent;

import tools.jackson.databind.ObjectMapper;

final class RabbitMessagePublisherTest {
    @Test
    void publishesOnlyNestedFrozenInferenceTaskWithTraceHeaders() throws Exception {
        ConfirmingRabbitTemplate rabbit = new ConfirmingRabbitTemplate();
        RabbitMessagePublisher publisher = new RabbitMessagePublisher(
            rabbit,
            Duration.ofSeconds(1),
            new ObjectMapper()
        );
        UUID taskId = UUID.randomUUID();
        OutboxEvent event = event(taskId, validPayload(taskId));

        publisher.publishAndConfirm(event);

        assertThat(rabbit.message).isNotNull();
        assertThat(rabbit.message.getMessageProperties().getType())
            .isEqualTo("tool_defect.inference.task.v1");
        String schemaVersion = rabbit.message.getMessageProperties().getHeader(
            "schema_version"
        );
        assertThat(schemaVersion).isEqualTo("1.0");
        assertThat(rabbit.message.getMessageProperties().getDeliveryMode())
            .isEqualTo(org.springframework.amqp.core.MessageDeliveryMode.PERSISTENT);
        assertThat(rabbit.message.getMessageProperties().getContentType())
            .isEqualTo("application/json");
        assertThat(rabbit.message.getMessageProperties().getHeaders())
            .containsOnlyKeys("schema_version", "traceparent");
        var delivered = new ObjectMapper().readTree(rabbit.message.getBody());
        assertThat(delivered.path("event_type").stringValue())
            .isEqualTo("tool_defect.inference.task.v1");
        assertThat(delivered.has("payload")).isFalse();
    }

    @Test
    void rejectsMissingFieldsUnknownFieldsAndWrongJsonTypesBeforeSend() {
        ConfirmingRabbitTemplate rabbit = new ConfirmingRabbitTemplate();
        RabbitMessagePublisher publisher = new RabbitMessagePublisher(
            rabbit,
            Duration.ofSeconds(1),
            new ObjectMapper()
        );
        UUID taskId = UUID.randomUUID();
        String valid = validPayload(taskId);

        assertThatThrownBy(() -> publisher.publishAndConfirm(event(
            taskId,
            valid.replace("\"images\":", "\"unknown\":true,\"images\":")
        ))).isInstanceOf(NonRetryableMessageException.class);
        assertThatThrownBy(() -> publisher.publishAndConfirm(event(
            taskId,
            valid.replace("\"version\":\"1\"", "\"version\":1")
        ))).isInstanceOf(NonRetryableMessageException.class);
        assertThatThrownBy(() -> publisher.publishAndConfirm(event(
            taskId,
            valid.replace("\"images\":[{", "\"images\":[] , \"removed\":[{")
        ))).isInstanceOf(NonRetryableMessageException.class);
        assertThat(rabbit.message).isNull();
    }

    @Test
    void publishesFrozenV2SingleItemWithoutMultiviewEnvelope() throws Exception {
        ConfirmingRabbitTemplate rabbit = new ConfirmingRabbitTemplate();
        RabbitMessagePublisher publisher = new RabbitMessagePublisher(
            rabbit, Duration.ofSeconds(1), new ObjectMapper());
        UUID taskId = UUID.randomUUID();
        String payload = """
            {"message_id":"019f0000-0000-7000-8000-000000000511",
             "occurred_at":"2026-08-03T00:00:00Z","idempotency_key":"r4-request-0001",
             "traceparent":"00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
             "batch_item_id":"019f0000-0000-7000-8000-000000000512",
             "detection_task_id":"%s",
             "image":{"bucket":"td-original","object_key":"manual-originals/r4/item.png",
               "sha256":"%s","size_bytes":128,"media_type":"image/png"},
             "pipeline_version":"2.0.0"}
            """.formatted(taskId, "c".repeat(64));
        OutboxEvent event = OutboxEvent.pending(
            UUID.randomUUID(), "detection_task", taskId,
            "tool_defect.inference.item.requested.v2",
            "inference.item.requested.v2", payload,
            Instant.parse("2026-08-03T00:00:00Z"));

        publisher.publishAndConfirm(event);

        assertThat(rabbit.message.getMessageProperties().getType())
            .isEqualTo("tool_defect.inference.item.requested.v2");
        String schemaVersion = rabbit.message.getMessageProperties()
            .getHeader("schema_version");
        assertThat(schemaVersion).isEqualTo("2.0");
        var delivered = new ObjectMapper().readTree(rabbit.message.getBody());
        assertThat(delivered.has("image")).isTrue();
        assertThat(delivered.has("images")).isFalse();
    }

    private static OutboxEvent event(UUID taskId, String payload) {
        UUID eventId = UUID.randomUUID();
        Instant occurredAt = Instant.parse("2026-07-29T00:00:00Z");
        String envelope = """
            {
              "event_id":"%s",
              "event_type":"tool_defect.outbox.inference_requested.v1",
              "aggregate_type":"detection_task",
              "aggregate_id":"%s",
              "occurred_at":"%s",
              "message_id":"019f0000-0000-7000-8000-000000000501",
              "traceparent":"00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
              "payload":%s
            }
            """.formatted(eventId, taskId, occurredAt, payload);
        return OutboxEvent.pending(
            eventId,
            "detection_task",
            taskId,
            "tool_defect.outbox.inference_requested.v1",
            "production.gpu.multitask",
            envelope,
            occurredAt
        );
    }

    private static String validPayload(UUID taskId) {
        return """
            {
              "event_type":"tool_defect.inference.task.v1",
              "message_id":"019f0000-0000-7000-8000-000000000501",
              "occurred_at":"2026-07-29T00:00:00Z",
              "traceparent":"00-0123456789abcdef0123456789abcdef-0123456789abcdef-01",
              "detection_task_id":"%s",
              "capture_id":"019f0000-0000-7000-8000-000000000502",
              "pipeline":{
                "pipeline_id":"019f0000-0000-7000-8000-000000000503",
                "version":"1",
                "config_sha256":"%s",
                "preprocessor_version":"1",
                "algorithm_version":"1",
                "model_version":"1"
              },
              "images":[{
                "image_id":"019f0000-0000-7000-8000-000000000504",
                "kind":"RAW",
                "object":{
                  "bucket":"td-raw",
                  "object_key":"raw/2026/07/29/sample.png",
                  "object_version":"v1",
                  "sha256":"%s",
                  "size_bytes":128,
                  "media_type":"image/png"
                },
                "width":2,
                "height":2,
                "image_role":"PRIMARY"
              }],
              "deadline_at":"2026-07-29T00:00:30Z"
            }
            """.formatted(taskId, "a".repeat(64), "b".repeat(64));
    }

    private static final class ConfirmingRabbitTemplate extends RabbitTemplate {
        private Message message;

        @Override
        public void send(
                String exchange,
                String routingKey,
                Message sent,
                CorrelationData correlationData) {
            this.message = sent;
            correlationData.getFuture().complete(
                new CorrelationData.Confirm(true, null)
            );
        }
    }
}
