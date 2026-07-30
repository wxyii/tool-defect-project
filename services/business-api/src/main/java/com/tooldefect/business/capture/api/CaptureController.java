package com.tooldefect.business.capture.api;

import static com.tooldefect.business.shared.api.ContractValues.*;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.tooldefect.business.capture.application.CaptureImageRegistration;
import com.tooldefect.business.capture.application.CaptureRegistration;
import com.tooldefect.business.capture.application.CaptureWorkflowService;
import com.tooldefect.business.shared.api.ContractValues;

@RestController
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
@RequestMapping("/api/v1/edge")
public final class CaptureController {
    private static final Set<String> CREATE_FIELDS = Set.of(
        "capture_id", "station_id", "trigger", "recipe_id", "quality", "images"
    );
    private static final Set<String> TRIGGER_FIELDS = Set.of(
        "trigger_id", "client_sequence", "occurred_at", "source"
    );
    private static final Set<String> QUALITY_FIELDS = Set.of("status", "warnings");
    private static final Set<String> IMAGE_FIELDS = Set.of(
        "client_image_id", "image_role", "file_name", "media_type",
        "size_bytes", "sha256", "width", "height"
    );
    private static final Set<String> COMPLETE_FIELDS = Set.of(
        "size_bytes", "sha256", "upload_receipt"
    );
    private static final Set<String> SUBMIT_FIELDS = Set.of("requested_at");
    private static final Set<String> SYNC_FIELDS = Set.of("capture_ids");
    private static final Set<String> HEARTBEAT_FIELDS = Set.of(
        "agent_version", "reported_at", "queue_depth",
        "oldest_task_age_seconds", "disk_usage_ratio", "camera_status",
        "plc_status", "clock_offset_ms"
    );

    private final CaptureWorkflowService captures;

    public CaptureController(CaptureWorkflowService captures) {
        this.captures = java.util.Objects.requireNonNull(captures);
    }

    @PostMapping("/captures")
    ResponseEntity<Map<String, Object>> createCapture(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        Map<String, Object> request = object(body, CREATE_FIELDS, "采集创建请求");
        UUID actorStationId = stationId(authentication);
        var registration = registration(request);
        var response = captures.create(
            registration,
            actorStationId,
            idempotencyKey,
            request
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/captures/{capture_id}/images/{image_id}/complete")
    ResponseEntity<Map<String, Object>> completeCaptureImage(
            @PathVariable("capture_id") UUID captureId,
            @PathVariable("image_id") UUID imageId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        Map<String, Object> request = object(
            body,
            COMPLETE_FIELDS,
            "图片确认请求"
        );
        var response = captures.completeImage(
            captureId,
            imageId,
            stationId(authentication),
            integer(request, "size_bytes", 1, Long.MAX_VALUE),
            sha256(request, "sha256"),
            text(request, "upload_receipt", 1, 512),
            idempotencyKey,
            request
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/captures/{capture_id}/submit")
    ResponseEntity<Map<String, Object>> submitCapture(
            @PathVariable("capture_id") UUID captureId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader("traceparent") String traceparent,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        Map<String, Object> request = object(body, SUBMIT_FIELDS, "检测提交请求");
        instant(request, "requested_at");
        var response = captures.submit(
            captureId,
            stationId(authentication),
            idempotencyKey,
            request,
            traceparent
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @GetMapping("/captures/{capture_id}")
    Map<String, Object> getEdgeCapture(
            @PathVariable("capture_id") UUID captureId,
            Authentication authentication) {
        return captures.get(captureId, stationId(authentication));
    }

    @PostMapping("/sync/captures/query")
    Map<String, Object> queryCaptureSync(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        requireIdempotencyKey(idempotencyKey);
        Map<String, Object> request = object(body, SYNC_FIELDS, "批量对账请求");
        Object values = request.get("capture_ids");
        if (!(values instanceof List<?> raw)
                || raw.isEmpty()
                || raw.size() > 100) {
            throw new ContractValues.ContractInputViolation(
                "capture_ids 数量必须为 1 到 100"
            );
        }
        List<UUID> ids = new ArrayList<>();
        for (Object value : raw) {
            try {
                ids.add(UUID.fromString(String.valueOf(value)));
            } catch (IllegalArgumentException invalid) {
                throw new ContractValues.ContractInputViolation(
                    "capture_ids 包含非法 UUID",
                    invalid
                );
            }
        }
        return captures.reconcile(ids, stationId(authentication));
    }

    @PostMapping("/devices/{device_id}/heartbeat")
    ResponseEntity<Map<String, Object>> reportDeviceHeartbeat(
            @PathVariable("device_id") UUID deviceId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        Map<String, Object> request = object(
            body,
            HEARTBEAT_FIELDS,
            "设备心跳请求"
        );
        text(request, "agent_version", 1, 128);
        instant(request, "reported_at");
        integer(request, "queue_depth", 0, Integer.MAX_VALUE);
        number(request, "oldest_task_age_seconds", 0, Double.MAX_VALUE);
        number(request, "disk_usage_ratio", 0, 1);
        oneOf(
            request,
            "camera_status",
            Set.of("ONLINE", "OFFLINE", "DEGRADED")
        );
        oneOf(
            request,
            "plc_status",
            Set.of("ONLINE", "OFFLINE", "DEGRADED")
        );
        number(
            request,
            "clock_offset_ms",
            -Double.MAX_VALUE,
            Double.MAX_VALUE
        );
        var response = captures.heartbeat(
            deviceId,
            stationId(authentication),
            text(request, "agent_version", 1, 128),
            instant(request, "reported_at"),
            request,
            idempotencyKey,
            request
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    private static CaptureRegistration registration(Map<String, Object> request) {
        Map<String, Object> trigger = object(
            request.get("trigger"),
            TRIGGER_FIELDS,
            "trigger"
        );
        Map<String, Object> quality = object(
            request.get("quality"),
            QUALITY_FIELDS,
            "quality"
        );
        List<Map<String, Object>> imageValues = objectList(
            request.get("images"),
            1,
            16,
            IMAGE_FIELDS,
            "images"
        );
        List<CaptureImageRegistration> images = new ArrayList<>();
        Set<String> clientIds = new HashSet<>();
        Set<String> roles = new HashSet<>();
        for (Map<String, Object> image : imageValues) {
            String clientId = text(image, "client_image_id", 1, 64);
            String role = text(image, "image_role", 1, 64);
            String fileName = text(image, "file_name", 1, 255);
            if (fileName.contains("/") || fileName.contains("\\")) {
                throw new ContractValues.ContractInputViolation(
                    "file_name 不得包含路径"
                );
            }
            if (!clientIds.add(clientId) || !roles.add(role)) {
                throw new ContractValues.ContractInputViolation(
                    "图片标识和角色在一次采集中必须唯一"
                );
            }
            images.add(new CaptureImageRegistration(
                clientId,
                role,
                fileName,
                oneOf(image, "media_type", Set.of("image/png", "image/jpeg")),
                integer(image, "size_bytes", 1, Long.MAX_VALUE),
                sha256(image, "sha256"),
                Math.toIntExact(integer(image, "width", 1, 32768)),
                Math.toIntExact(integer(image, "height", 1, 32768))
            ));
        }
        return new CaptureRegistration(
            uuid(request, "capture_id"),
            uuid(request, "station_id"),
            uuid(request, "recipe_id"),
            text(trigger, "trigger_id", 1, 128),
            integer(trigger, "client_sequence", 0, Long.MAX_VALUE),
            instant(trigger, "occurred_at"),
            oneOf(
                trigger,
                "source",
                Set.of("PLC", "SENSOR", "MANUAL", "HISTORICAL_IMPORT")
            ),
            oneOf(quality, "status", Set.of("OK", "WARNING", "REJECTED")),
            strings(quality, "warnings", 32, 128),
            images
        );
    }

    private static UUID stationId(Authentication authentication) {
        if (authentication == null
                || !(authentication.getPrincipal() instanceof Jwt jwt)) {
            throw new CaptureIdentityViolation("设备身份缺少 JWT 工位范围");
        }
        try {
            return UUID.fromString(jwt.getClaimAsString("station_id"));
        } catch (RuntimeException invalid) {
            throw new CaptureIdentityViolation(
                "设备身份缺少合法 station_id",
                invalid
            );
        }
    }

    private static void requireIdempotencyKey(String value) {
        if (value == null || value.length() < 8 || value.length() > 256) {
            throw new ContractValues.ContractInputViolation(
                "Idempotency-Key 不合法"
            );
        }
    }

    public static final class CaptureIdentityViolation extends RuntimeException {
        CaptureIdentityViolation(String message) {
            super(message);
        }

        CaptureIdentityViolation(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
