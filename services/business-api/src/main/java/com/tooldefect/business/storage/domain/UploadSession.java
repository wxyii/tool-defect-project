package com.tooldefect.business.storage.domain;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

import com.tooldefect.business.shared.domain.DomainViolation;

public record UploadSession(
        UUID uploadSessionId,
        UUID imageId,
        UUID captureId,
        UUID stationId,
        String receiptSha256,
        long expectedSizeBytes,
        String expectedSha256,
        String expectedMediaType,
        UploadSessionStatus status,
        Instant expiresAt) {

    public UploadSession {
        Objects.requireNonNull(uploadSessionId);
        Objects.requireNonNull(imageId);
        Objects.requireNonNull(captureId);
        Objects.requireNonNull(stationId);
        requireSha256(receiptSha256, "票据摘要");
        requireSha256(expectedSha256, "对象摘要");
        if (expectedSizeBytes <= 0) {
            throw new DomainViolation("对象大小必须大于 0");
        }
        if (expectedMediaType == null || expectedMediaType.isBlank()) {
            throw new DomainViolation("媒体类型不能为空");
        }
        Objects.requireNonNull(status);
        Objects.requireNonNull(expiresAt);
    }

    public boolean receiptMatches(String actualReceiptSha256) {
        if (actualReceiptSha256 == null) {
            return false;
        }
        return MessageDigest.isEqual(
            receiptSha256.getBytes(StandardCharsets.US_ASCII),
            actualReceiptSha256.getBytes(StandardCharsets.US_ASCII)
        );
    }

    public boolean requestMatches(long sizeBytes, String sha256) {
        return expectedSizeBytes == sizeBytes && expectedSha256.equals(sha256);
    }

    public boolean expiredAt(Instant now) {
        return !now.isBefore(expiresAt);
    }

    private static void requireSha256(String value, String field) {
        if (value == null || !value.matches("[0-9a-f]{64}")) {
            throw new DomainViolation(field + "不是合法 SHA-256");
        }
    }
}
