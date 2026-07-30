package com.tooldefect.business.review.application;

import java.util.Objects;

import com.tooldefect.business.shared.domain.DomainViolation;

public record ReviewRequestContext(
        String actorId,
        String requestId,
        String traceId) {
    public ReviewRequestContext {
        requireText(actorId, "复核参与者");
        requireText(requestId, "请求标识");
        if (traceId == null || !traceId.matches("[0-9a-f]{32}")) {
            throw new DomainViolation("追踪标识必须是 32 位小写十六进制值");
        }
    }

    private static void requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new DomainViolation(field + "不能为空");
        }
    }
}
