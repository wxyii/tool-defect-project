package com.tooldefect.business.storage.api;

import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.storage.application.ImageAccessService;

@RestController
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
@RequestMapping("/api/v1/images")
public final class ImageAccessController {
    private static final Set<String> FIELDS = Set.of("purpose");
    private final ImageAccessService images;

    public ImageAccessController(ImageAccessService images) {
        this.images = java.util.Objects.requireNonNull(images);
    }

    @PostMapping("/{image_id}/access-ticket")
    ResponseEntity<Map<String, Object>> createImageAccessTicket(
            @PathVariable("image_id") UUID imageId,
            @RequestBody Map<String, Object> request,
            @RequestHeader(
                value = "X-Request-ID",
                required = false
            ) String requestId,
            @RequestHeader(
                value = "traceparent",
                required = false
            ) String traceparent,
            Authentication authentication) {
        if (request == null || !request.keySet().equals(FIELDS)) {
            throw new ContractInputViolation(
                "图片访问请求字段必须严格匹配 v1 契约"
            );
        }
        Object rawPurpose = request.get("purpose");
        if (!(rawPurpose instanceof String purpose)
                || (!"VIEW".equals(purpose)
                    && !"DOWNLOAD".equals(purpose))) {
            throw new ContractInputViolation("图片访问用途不合法");
        }
        if (authentication == null
                || authentication.getName() == null
                || authentication.getName().isBlank()) {
            throw new StorageIdentityViolation("用户身份缺失");
        }
        String stableRequestId = requestId;
        if (stableRequestId == null
                || stableRequestId.isBlank()
                || stableRequestId.length() > 128) {
            stableRequestId = UUID.randomUUID().toString();
        }
        var ticket = images.issue(
            imageId,
            authentication.getName(),
            purpose,
            stableRequestId,
            traceId(traceparent, stableRequestId)
        );
        return ResponseEntity.ok(Map.of(
            "method", "GET",
            "url", ticket.url().toString(),
            "expires_at",
                DateTimeFormatter.ISO_INSTANT.format(ticket.expiresAt())
        ));
    }

    private static String traceId(String traceparent, String requestId) {
        if (traceparent != null
                && traceparent.matches(
                    "^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
                )) {
            return traceparent.split("-")[1];
        }
        Map<String, Object> input = new LinkedHashMap<>();
        input.put("request_id", requestId);
        return CanonicalJson.sha256(input).substring(0, 32);
    }

    public static final class ContractInputViolation extends RuntimeException {
        ContractInputViolation(String message) {
            super(message);
        }
    }

    public static final class StorageIdentityViolation
            extends RuntimeException {
        StorageIdentityViolation(String message) {
            super(message);
        }
    }
}
