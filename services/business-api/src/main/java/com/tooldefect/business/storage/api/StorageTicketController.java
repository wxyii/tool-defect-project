package com.tooldefect.business.storage.api;

import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import org.springframework.http.ResponseEntity;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.tooldefect.business.storage.application.UploadTicketRenewal;

/**
 * v1 契约使用生成包所采用的 Map 网络形状；字段名、额外字段拒绝规则和
 * 响应结构均直接对应冻结 OpenAPI，不在控制器内复制另一套 DTO。
 */
@RestController
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
@RequestMapping("/api/v1/edge/captures/{capture_id}/images/{image_id}")
public final class StorageTicketController {
    private static final Set<String> RENEW_FIELDS = Set.of("size_bytes", "sha256");

    private final UploadTicketRenewal storage;

    public StorageTicketController(UploadTicketRenewal storage) {
        this.storage = java.util.Objects.requireNonNull(storage);
    }

    @PostMapping("/upload-ticket")
    ResponseEntity<Map<String, Object>> renewCaptureImageUploadTicket(
            @PathVariable("capture_id") UUID captureId,
            @PathVariable("image_id") UUID imageId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> request,
            Authentication authentication) {
        requireIdempotencyKey(idempotencyKey);
        if (request == null || !request.keySet().equals(RENEW_FIELDS)) {
            throw new ContractInputViolation("续签请求字段必须严格匹配 v1 契约");
        }
        long sizeBytes = requirePositiveLong(request.get("size_bytes"));
        String sha256 = requireSha256(request.get("sha256"));
        UUID actorStationId = requireStationIdentity(authentication);
        var ticket = storage.renewRawUpload(
            imageId,
            captureId,
            actorStationId,
            sizeBytes,
            sha256
        );

        Map<String, Object> upload = new LinkedHashMap<>();
        upload.put("method", ticket.method());
        upload.put("url", ticket.url().toString());
        upload.put("headers", ticket.headers());
        upload.put(
            "expires_at",
            DateTimeFormatter.ISO_INSTANT.format(ticket.expiresAt())
        );
        return ResponseEntity.ok(Map.of(
            "image_id", imageId.toString(),
            "upload", Map.copyOf(upload)
        ));
    }

    private static UUID requireStationIdentity(Authentication authentication) {
        if (authentication == null || !(authentication.getPrincipal() instanceof Jwt jwt)) {
            throw new StorageIdentityViolation("设备身份缺少 JWT 站点范围");
        }
        String value = jwt.getClaimAsString("station_id");
        try {
            return UUID.fromString(value);
        } catch (RuntimeException invalid) {
            throw new StorageIdentityViolation("设备身份缺少合法 station_id", invalid);
        }
    }

    private static long requirePositiveLong(Object value) {
        if (!(value instanceof Number number)) {
            throw new ContractInputViolation("size_bytes 必须是正整数");
        }
        long converted = number.longValue();
        if (converted <= 0 || converted != number.doubleValue()) {
            throw new ContractInputViolation("size_bytes 必须是正整数");
        }
        return converted;
    }

    private static String requireSha256(Object value) {
        if (!(value instanceof String text) || !text.matches("[0-9a-f]{64}")) {
            throw new ContractInputViolation("sha256 不符合 v1 契约");
        }
        return text;
    }

    private static void requireIdempotencyKey(String value) {
        if (value == null || value.length() < 8 || value.length() > 256) {
            throw new ContractInputViolation("Idempotency-Key 不合法");
        }
    }

    public static final class ContractInputViolation extends RuntimeException {
        ContractInputViolation(String message) {
            super(message);
        }
    }

    public static final class StorageIdentityViolation extends RuntimeException {
        StorageIdentityViolation(String message) {
            super(message);
        }

        StorageIdentityViolation(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
