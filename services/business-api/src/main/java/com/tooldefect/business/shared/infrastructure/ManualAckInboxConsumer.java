package com.tooldefect.business.shared.infrastructure;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Objects;
import java.util.UUID;

import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import com.rabbitmq.client.Channel;
import com.tooldefect.business.shared.application.BusinessMessageHandler;
import com.tooldefect.business.shared.application.InboxProcessingService;
import com.tooldefect.business.shared.application.NonRetryableMessageException;
import com.tooldefect.business.shared.domain.DomainViolation;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 先在同一数据库事务内完成收件箱和业务效果，再手动确认 RabbitMQ 消息。
 * 暂时故障重新入队；契约或哈希冲突直接进入队列配置的死信交换机。
 */
@Component
@ConditionalOnProperty(
    name = "td.messaging.consumer.enabled",
    havingValue = "true"
)
public final class ManualAckInboxConsumer {
    private final InboxProcessingService inbox;
    private final BusinessMessageHandler handler;
    private final MessagingProperties properties;
    private final ObjectMapper json;

    public ManualAckInboxConsumer(
            InboxProcessingService inbox,
            BusinessMessageHandler handler,
            MessagingProperties properties,
            ObjectMapper json) {
        this.inbox = Objects.requireNonNull(inbox);
        this.handler = Objects.requireNonNull(handler);
        this.properties = Objects.requireNonNull(properties);
        this.json = Objects.requireNonNull(json);
    }

    @RabbitListener(queues = "${td.messaging.consumer.queue}")
    public void consume(Message message, Channel channel) throws IOException {
        long deliveryTag = message.getMessageProperties().getDeliveryTag();
        try {
            String payload = new String(message.getBody(), StandardCharsets.UTF_8);
            JsonNode root = json.readTree(payload);
            String messageId = requiredText(root, "message_id");
            UUID detectionTaskId = UUID.fromString(
                requiredText(root, "detection_task_id")
            );
            String resultSha256 = optionalSha256(root);
            var result = inbox.process(
                messageId,
                properties.consumer().name(),
                detectionTaskId,
                resultSha256,
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

    private static String requiredText(JsonNode root, String field) {
        String value = root.path(field).asString(null);
        if (value == null || value.isBlank()) {
            throw new NonRetryableMessageException("消息缺少字段：" + field);
        }
        return value;
    }

    private static String optionalSha256(JsonNode root) {
        String value = root.path("result_sha256").asString(null);
        if (value == null) {
            return null;
        }
        if (!value.matches("[0-9a-f]{64}")) {
            throw new NonRetryableMessageException("result_sha256 不合法");
        }
        return value;
    }
}
