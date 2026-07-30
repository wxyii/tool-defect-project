package com.tooldefect.business.storage.web;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.TestingAuthenticationToken;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import com.tooldefect.business.storage.api.StorageTicketController;
import com.tooldefect.business.storage.domain.StorageTicketExpired;
import com.tooldefect.business.storage.infrastructure.StorageApiExceptionHandler;

/** 锁定续传票据接口的 v1 错误体和可恢复错误码。 */
final class StorageTicketControllerTest {
    private static final UUID CAPTURE_ID = UUID.fromString(
        "019f0000-0000-7000-8000-000000000401"
    );
    private static final UUID IMAGE_ID = UUID.fromString(
        "019f0000-0000-7000-8000-000000000402"
    );
    private static final UUID STATION_ID = UUID.fromString(
        "019f0000-0000-7000-8000-000000000403"
    );
    private static final String REQUEST_ID =
        "019f0000-0000-7000-8000-000000000404";
    private static final String TRACE_ID =
        "0123456789abcdef0123456789abcdef";

    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        var controller = new StorageTicketController(
            (imageId, captureId, actorStationId, sizeBytes, sha256) -> {
                throw new StorageTicketExpired("上传授权已过期，必须重新申请");
            }
        );
        mvc = MockMvcBuilders.standaloneSetup(controller)
            .setControllerAdvice(new StorageApiExceptionHandler())
            .build();
    }

    @Test
    void expiredTicketHasDedicatedRecoverableContractError() throws Exception {
        var authentication = authentication();

        mvc.perform(post(
                "/api/v1/edge/captures/{capture_id}/images/{image_id}/upload-ticket",
                CAPTURE_ID,
                IMAGE_ID
            )
                .principal(authentication)
                .header("Idempotency-Key", "renew-after-expiry")
                .header("X-Request-Id", REQUEST_ID)
                .header(
                    "traceparent",
                    "00-" + TRACE_ID + "-0123456789abcdef-01"
                )
                .contentType(MediaType.APPLICATION_JSON)
                .content(validBody()))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.code").value("TD-STORAGE-EXPIRED-001"))
            .andExpect(jsonPath("$.message").value(
                "上传授权已过期，必须重新申请"
            ))
            .andExpect(jsonPath("$.request_id").value(REQUEST_ID))
            .andExpect(jsonPath("$.trace_id").value(TRACE_ID))
            .andExpect(jsonPath("$.retryable").value(true))
            .andExpect(jsonPath("$.details").isArray())
            .andExpect(jsonPath("$.details").isEmpty());
    }

    @Test
    void idempotencyKeyLengthFollowsFrozenOpenApi() throws Exception {
        mvc.perform(post(
                "/api/v1/edge/captures/{capture_id}/images/{image_id}/upload-ticket",
                CAPTURE_ID,
                IMAGE_ID
            )
                .principal(authentication())
                .header("Idempotency-Key", "short")
                .contentType(MediaType.APPLICATION_JSON)
                .content(validBody()))
            .andExpect(status().isUnprocessableContent())
            .andExpect(jsonPath("$.code").value("TD-API-VALIDATION-001"));

        mvc.perform(post(
                "/api/v1/edge/captures/{capture_id}/images/{image_id}/upload-ticket",
                CAPTURE_ID,
                IMAGE_ID
            )
                .principal(authentication())
                .header("Idempotency-Key", "k".repeat(256))
                .contentType(MediaType.APPLICATION_JSON)
                .content(validBody()))
            .andExpect(status().isConflict())
            .andExpect(jsonPath("$.code").value("TD-STORAGE-EXPIRED-001"));
    }

    @Test
    void bindingFailuresAlsoUseStandardErrorContract() throws Exception {
        mvc.perform(post(
                "/api/v1/edge/captures/{capture_id}/images/{image_id}/upload-ticket",
                CAPTURE_ID,
                IMAGE_ID
            )
                .principal(authentication())
                .contentType(MediaType.APPLICATION_JSON)
                .content(validBody()))
            .andExpect(status().isBadRequest())
            .andExpect(jsonPath("$.code").value("TD-API-VALIDATION-001"))
            .andExpect(jsonPath("$.request_id").isString())
            .andExpect(jsonPath("$.trace_id").isString())
            .andExpect(jsonPath("$.retryable").value(false))
            .andExpect(jsonPath("$.details").isArray());

        mvc.perform(post(
                "/api/v1/edge/captures/not-a-uuid/images/{image_id}/upload-ticket",
                IMAGE_ID
            )
                .principal(authentication())
                .header("Idempotency-Key", "valid-key")
                .contentType(MediaType.APPLICATION_JSON)
                .content(validBody()))
            .andExpect(status().isBadRequest())
            .andExpect(jsonPath("$.code").value("TD-API-VALIDATION-001"));

        mvc.perform(post(
                "/api/v1/edge/captures/{capture_id}/images/{image_id}/upload-ticket",
                CAPTURE_ID,
                IMAGE_ID
            )
                .principal(authentication())
                .header("Idempotency-Key", "valid-key")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{not-json"))
            .andExpect(status().isBadRequest())
            .andExpect(jsonPath("$.code").value("TD-API-VALIDATION-001"));
    }

    private static TestingAuthenticationToken authentication() {
        Jwt jwt = Jwt.withTokenValue("test-token")
            .header("alg", "none")
            .subject("edge-device")
            .claim("station_id", STATION_ID.toString())
            .issuedAt(Instant.parse("2026-07-29T00:00:00Z"))
            .expiresAt(Instant.parse("2026-07-30T00:00:00Z"))
            .build();
        return new TestingAuthenticationToken(
            jwt,
            null,
            "SCOPE_capture:write"
        );
    }

    private static String validBody() {
        return "{\"size_bytes\":123,\"sha256\":\""
            + "a".repeat(64)
            + "\"}";
    }
}
