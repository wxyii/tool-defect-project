package com.tooldefect.business.audit.domain;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

import com.tooldefect.business.shared.domain.DomainViolation;

/** 只追加的业务审计记录。 */
public record AuditRecord(
        UUID auditId,
        Instant occurredAt,
        String actorType,
        String actorId,
        String action,
        String resourceType,
        String resourceId,
        String beforeDigest,
        String afterDigest,
        String reason,
        String requestId,
        String traceId,
        String result,
        String errorCode) {

    public AuditRecord {
        Objects.requireNonNull(auditId);
        Objects.requireNonNull(occurredAt);
        requireText(actorType, "actorType");
        requireText(actorId, "actorId");
        requireText(action, "action");
        requireText(resourceType, "resourceType");
        requireText(resourceId, "resourceId");
        requireText(requestId, "requestId");
        requireText(traceId, "traceId");
        requireText(result, "result");
    }

    private static void requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new DomainViolation(field + " 不能为空");
        }
    }
}
