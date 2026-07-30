package com.tooldefect.business.review.application;

import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import com.tooldefect.business.review.domain.ReviewStatus;
import com.tooldefect.business.shared.domain.DomainViolation;

public record ReviewTaskState(
        UUID reviewTaskId,
        UUID captureId,
        int priority,
        ReviewStatus status,
        String claimedBy,
        Instant leaseExpiresAt,
        ReviewStatus claimedFromStatus,
        boolean requiresSecondReview,
        long recordVersion,
        UUID revisionOfTaskId,
        UUID supersedesReviewRecordId,
        Instant createdAt) {

    public ReviewTaskState {
        Objects.requireNonNull(reviewTaskId);
        Objects.requireNonNull(captureId);
        Objects.requireNonNull(status);
        Objects.requireNonNull(createdAt);
        priorityLabel(priority);
        if (recordVersion < 0) {
            throw new DomainViolation("复核任务版本不能为负数");
        }
    }

    public Map<String, Object> contractView() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("review_task_id", reviewTaskId.toString());
        result.put("capture_id", captureId.toString());
        result.put("status", status.name());
        result.put("priority", priorityLabel(priority));
        result.put(
            "lease_expires_at",
            leaseExpiresAt == null
                ? null
                : DateTimeFormatter.ISO_INSTANT.format(leaseExpiresAt)
        );
        result.put("record_version", recordVersion);
        return Collections.unmodifiableMap(result);
    }

    public static int priorityValue(String priority) {
        return switch (Objects.requireNonNull(priority)) {
            case "P0" -> 0;
            case "P1" -> 10;
            case "P2" -> 20;
            case "P3" -> 30;
            default -> throw new DomainViolation("复核优先级不合法");
        };
    }

    public static String priorityLabel(int priority) {
        return switch (priority) {
            case 0 -> "P0";
            case 10 -> "P1";
            case 20 -> "P2";
            case 30 -> "P3";
            default -> throw new DomainViolation("数据库复核优先级不合法");
        };
    }
}
