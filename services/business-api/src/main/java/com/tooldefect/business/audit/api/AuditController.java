package com.tooldefect.business.audit.api;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.tooldefect.business.audit.application.AuditQueryService;
import com.tooldefect.business.shared.api.ContractValues;
import com.tooldefect.business.shared.application.CanonicalJson;

@RestController
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
@RequestMapping("/api/v1/audit-records")
public final class AuditController {
    private static final Duration DEFAULT_WINDOW = Duration.ofHours(24);
    private static final Duration MAXIMUM_WINDOW = Duration.ofDays(31);

    private final AuditQueryService audit;
    private final Clock clock;

    public AuditController(AuditQueryService audit, Clock clock) {
        this.audit = Objects.requireNonNull(audit);
        this.clock = Objects.requireNonNull(clock);
    }

    @GetMapping
    ResponseEntity<Map<String, Object>> list(
            @RequestParam(name = "cursor", required = false) String cursor,
            @RequestParam(name = "page_size", defaultValue = "50") int pageSize,
            @RequestParam(name = "start_time", required = false) String startTime,
            @RequestParam(name = "end_time", required = false) String endTime,
            @RequestParam(name = "actor_id", required = false) String actorId,
            @RequestParam(name = "action", required = false) String action,
            @RequestParam(name = "resource_type", required = false)
            String resourceType,
            @RequestParam(name = "resource_id", required = false)
            String resourceId,
            @RequestParam(name = "result", required = false) String result,
            @RequestHeader(name = "X-Request-Id", required = false)
            String requestId,
            @RequestHeader(name = "traceparent", required = false)
            String traceparent,
            Authentication authentication,
            HttpServletRequest request) {
        if (pageSize < 1 || pageSize > 200) {
            throw new ContractValues.ContractInputViolation(
                "page_size 必须位于 1 到 200"
            );
        }
        Instant now = Instant.now(clock);
        Instant end = instant(endTime, "end_time", now);
        Instant start = instant(startTime, "start_time", end.minus(DEFAULT_WINDOW));
        if (!start.isBefore(end)) {
            throw new ContractValues.ContractInputViolation(
                "start_time 必须早于 end_time"
            );
        }
        if (Duration.between(start, end).compareTo(MAXIMUM_WINDOW) > 0) {
            throw new ContractValues.ContractInputViolation(
                "审计查询窗口不能超过 31 天"
            );
        }
        String stableRequestId = requestId(requestId);
        return ResponseEntity.ok(audit.list(
            start,
            end,
            optionalCursor(cursor),
            pageSize,
            optionalText(actorId, "actor_id", 256),
            optionalText(action, "action", 128),
            optionalText(resourceType, "resource_type", 128),
            optionalText(resourceId, "resource_id", 256),
            optionalText(result, "result", 24),
            actor(authentication),
            remoteAddress(request),
            stableRequestId,
            traceId(traceparent, stableRequestId)
        ));
    }

    private static Instant instant(String value, String field, Instant fallback) {
        if (value == null) {
            return fallback;
        }
        if (value.isBlank() || !value.endsWith("Z")) {
            throw new ContractValues.ContractInputViolation(
                field + " 必须是 UTC 时间"
            );
        }
        try {
            return Instant.parse(value);
        } catch (DateTimeParseException invalid) {
            throw new ContractValues.ContractInputViolation(
                field + " 时间格式不合法",
                invalid
            );
        }
    }

    private static String optionalText(String value, String field, int maximum) {
        if (value == null) {
            return null;
        }
        if (value.isBlank() || value.length() > maximum) {
            throw new ContractValues.ContractInputViolation(field + " 不合法");
        }
        return value;
    }

    private static String optionalCursor(String cursor) {
        if (cursor == null) {
            return null;
        }
        if (cursor.isBlank() || cursor.length() > 512) {
            throw new ContractValues.ContractInputViolation("cursor 不合法");
        }
        return cursor;
    }

    private static String actor(Authentication authentication) {
        if (authentication == null
                || authentication.getName() == null
                || authentication.getName().isBlank()) {
            throw new IllegalStateException("审计查询缺少认证身份");
        }
        return authentication.getName();
    }

    private static String requestId(String value) {
        if (value == null || value.isBlank() || value.length() > 128) {
            return UUID.randomUUID().toString();
        }
        return value;
    }

    private static String traceId(String traceparent, String requestId) {
        if (traceparent != null
                && traceparent.matches(
                    "^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
                )) {
            return traceparent.split("-")[1];
        }
        Map<String, Object> source = new LinkedHashMap<>();
        source.put("request_id", requestId);
        return CanonicalJson.sha256(source).substring(0, 32);
    }

    private static String remoteAddress(HttpServletRequest request) {
        String value = request.getRemoteAddr();
        return value == null || value.isBlank() || value.length() > 64
            ? null
            : value;
    }
}
