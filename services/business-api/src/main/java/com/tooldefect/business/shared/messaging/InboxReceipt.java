package com.tooldefect.business.shared.messaging;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

import com.tooldefect.business.shared.domain.DomainViolation;

public record InboxReceipt(
        String messageId,
        String consumer,
        UUID detectionTaskId,
        String resultSha256,
        InboxStatus status,
        String claimOwner,
        Instant leaseUntil,
        int attemptCount,
        Instant receivedAt,
        Instant processedAt,
        String lastError) {

    public InboxReceipt {
        messageId = requireText(messageId, "messageId");
        consumer = requireText(consumer, "consumer");
        Objects.requireNonNull(detectionTaskId);
        if (resultSha256 != null && !resultSha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("resultSha256 不合法");
        }
        Objects.requireNonNull(status);
        Objects.requireNonNull(receivedAt);
        if (attemptCount < 0) {
            throw new DomainViolation("收件箱尝试次数不能为负数");
        }
        switch (status) {
            case PROCESSING -> {
                requireText(claimOwner, "claimOwner");
                Objects.requireNonNull(leaseUntil);
                if (processedAt != null) {
                    throw new DomainViolation("处理中消息不能已有处理时间");
                }
            }
            case PROCESSED -> {
                Objects.requireNonNull(processedAt);
                if (claimOwner != null || leaseUntil != null) {
                    throw new DomainViolation("已处理消息不能保留租约");
                }
            }
            case FAILED -> {
                if (claimOwner != null || leaseUntil != null || processedAt != null) {
                    throw new DomainViolation("失败消息不能保留处理租约");
                }
            }
        }
    }

    private static String requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new DomainViolation(field + " 不能为空");
        }
        return value;
    }
}
