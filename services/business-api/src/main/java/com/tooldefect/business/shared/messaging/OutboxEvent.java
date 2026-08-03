package com.tooldefect.business.shared.messaging;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

import com.tooldefect.business.shared.domain.DomainViolation;

/**
 * 发件箱持久化快照。领取、重试和发布状态由数据库比较并交换，避免应用进程
 * 在发布成功后崩溃时把内存状态误当作事实。
 */
public record OutboxEvent(
        UUID eventId,
        String aggregateType,
        UUID aggregateId,
        String eventType,
        String routingKey,
        String payloadJson,
        OutboxStatus status,
        int attemptCount,
        Instant nextAttemptAt,
        Instant createdAt,
        Instant publishedAt,
        String claimOwner,
        Instant leaseUntil,
        String lastError) {

    public OutboxEvent {
        Objects.requireNonNull(eventId);
        aggregateType = requireText(aggregateType, "aggregateType");
        Objects.requireNonNull(aggregateId);
        eventType = requireText(eventType, "eventType");
        if (!eventType.matches("^tool_defect\\.[a-z0-9_.]+\\.v[12]$")) {
            throw new DomainViolation("事件类型必须携带受支持的主版本");
        }
        routingKey = requireText(routingKey, "routingKey");
        if (!routingKey.matches("(production|shadow|batch)\\.(cpu|gpu)\\.(multitask|polar)")
                && !routingKey.equals("inference.item.requested.v2")) {
            throw new DomainViolation("推理路由键不在冻结契约范围");
        }
        payloadJson = requireText(payloadJson, "payload");
        rejectBinaryPayload(payloadJson);
        Objects.requireNonNull(status);
        if (attemptCount < 0) {
            throw new DomainViolation("尝试次数不能为负数");
        }
        Objects.requireNonNull(nextAttemptAt);
        Objects.requireNonNull(createdAt);
        validateState(status, publishedAt, claimOwner, leaseUntil);
        if (lastError != null && lastError.length() > 512) {
            throw new DomainViolation("发布错误摘要过长");
        }
    }

    public static OutboxEvent pending(
            UUID eventId,
            String aggregateType,
            UUID aggregateId,
            String eventType,
            String routingKey,
            String payloadJson,
            Instant createdAt) {
        return new OutboxEvent(
            eventId,
            aggregateType,
            aggregateId,
            eventType,
            routingKey,
            payloadJson,
            OutboxStatus.NEW,
            0,
            createdAt,
            createdAt,
            null,
            null,
            null,
            null
        );
    }

    private static void validateState(
            OutboxStatus status,
            Instant publishedAt,
            String claimOwner,
            Instant leaseUntil) {
        switch (status) {
            case CLAIMED -> {
                requireText(claimOwner, "claimOwner");
                Objects.requireNonNull(leaseUntil, "CLAIMED 必须有租约");
                if (publishedAt != null) {
                    throw new DomainViolation("已领取事件不能已有发布时间");
                }
            }
            case PUBLISHED -> {
                Objects.requireNonNull(publishedAt, "PUBLISHED 必须有发布时间");
                if (claimOwner != null || leaseUntil != null) {
                    throw new DomainViolation("已发布事件不能保留领取租约");
                }
            }
            case NEW, FAILED, DEAD -> {
                if (publishedAt != null || claimOwner != null || leaseUntil != null) {
                    throw new DomainViolation("待发布事件不能有发布或领取状态");
                }
            }
        }
    }

    private static void rejectBinaryPayload(String payload) {
        String normalized = decodeJsonEscapes(payload)
            .toLowerCase(java.util.Locale.ROOT);
        if (normalized.contains("\"base64\"")
                || normalized.contains("data:image/")
                || normalized.contains("\"image_bytes\"")) {
            throw new DomainViolation("消息只能传对象引用，不能传图片二进制");
        }
    }

    private static String decodeJsonEscapes(String value) {
        StringBuilder decoded = new StringBuilder(value.length());
        for (int index = 0; index < value.length(); index++) {
            char current = value.charAt(index);
            if (current != '\\' || index + 1 >= value.length()) {
                decoded.append(current);
                continue;
            }
            char escaped = value.charAt(++index);
            if (escaped == 'u' && index + 4 < value.length()) {
                String hex = value.substring(index + 1, index + 5);
                try {
                    decoded.append((char) Integer.parseInt(hex, 16));
                    index += 4;
                    continue;
                } catch (NumberFormatException ignored) {
                    decoded.append('\\').append(escaped);
                    continue;
                }
            }
            decoded.append(switch (escaped) {
                case '/', '\\', '"' -> escaped;
                case 'b' -> '\b';
                case 'f' -> '\f';
                case 'n' -> '\n';
                case 'r' -> '\r';
                case 't' -> '\t';
                default -> '\\';
            });
            if ("/\\\"bfnrt".indexOf(escaped) < 0) {
                decoded.append(escaped);
            }
        }
        return decoded.toString();
    }

    private static String requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new DomainViolation(field + " 不能为空");
        }
        return value;
    }
}
