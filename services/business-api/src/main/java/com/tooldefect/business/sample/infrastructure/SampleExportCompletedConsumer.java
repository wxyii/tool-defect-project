package com.tooldefect.business.sample.infrastructure;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import com.rabbitmq.client.Channel;
import com.tooldefect.business.shared.application.InboxProcessingService;
import com.tooldefect.business.shared.application.NonRetryableMessageException;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.infrastructure.RabbitTopology;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** R7 完成事件独立监听；收件箱事务成功后才确认 RabbitMQ 消息。 */
@Component
@ConditionalOnProperty(
    name = {"td.messaging.consumer.enabled", "td.sample-export.enabled", "td.storage.enabled"},
    havingValue = "true"
)
public final class SampleExportCompletedConsumer {
    private static final String CONSUMER = "sample-export-completed-v2";
    private final InboxProcessingService inbox;
    private final SampleExportCompletedHandler handler;
    private final ObjectMapper json;

    public SampleExportCompletedConsumer(
            InboxProcessingService inbox,
            SampleExportCompletedHandler handler,
            ObjectMapper json) {
        this.inbox = java.util.Objects.requireNonNull(inbox);
        this.handler = java.util.Objects.requireNonNull(handler);
        this.json = java.util.Objects.requireNonNull(json);
    }

    @RabbitListener(queues = RabbitTopology.SAMPLE_EXPORT_COMPLETED_V2_QUEUE)
    public void consume(Message message, Channel channel) throws IOException {
        long deliveryTag = message.getMessageProperties().getDeliveryTag();
        try {
            String payload = new String(message.getBody(), StandardCharsets.UTF_8);
            JsonNode root = json.readTree(payload);
            String messageId = requiredText(root, "message_id");
            String manifestSha256 = requiredText(root.path("manifest"), "sha256");
            if (!manifestSha256.matches("[0-9a-f]{64}")) {
                throw new NonRetryableMessageException("完成事件清单 SHA-256 不合法");
            }
            InboxProcessingService.Result result = inbox.process(
                messageId, CONSUMER, null, manifestSha256,
                () -> handler.handle(payload)
            );
            if (result == InboxProcessingService.Result.BUSY) {
                channel.basicNack(deliveryTag, false, true);
            } else {
                channel.basicAck(deliveryTag, false);
            }
        } catch (NonRetryableMessageException
                | DomainViolation
                | tools.jackson.core.JacksonException
                | IllegalArgumentException poison) {
            channel.basicNack(deliveryTag, false, false);
        } catch (RuntimeException transientFailure) {
            channel.basicNack(deliveryTag, false, true);
        }
    }

    private static String requiredText(JsonNode node, String field) {
        if (node == null || !node.path(field).isString()
                || node.path(field).stringValue().isBlank()) {
            throw new NonRetryableMessageException("完成事件缺少字段：" + field);
        }
        return node.path(field).stringValue();
    }
}
