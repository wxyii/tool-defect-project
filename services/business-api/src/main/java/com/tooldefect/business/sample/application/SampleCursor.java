package com.tooldefect.business.sample.application;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;
import java.util.UUID;

/** R7 列表游标的稳定编码；游标格式属于应用契约，不属于 JDBC 实现。 */
public final class SampleCursor {
    private SampleCursor() {}

    public static String encode(Instant createdAt, UUID id) {
        String value = createdAt + "|" + id;
        return Base64.getUrlEncoder().withoutPadding()
            .encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }

    public static Boundary decode(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            String decoded = new String(
                Base64.getUrlDecoder().decode(value), StandardCharsets.UTF_8);
            String[] parts = decoded.split("\\|", -1);
            if (parts.length != 2) {
                throw new IllegalArgumentException("invalid cursor shape");
            }
            return new Boundary(Instant.parse(parts[0]), UUID.fromString(parts[1]));
        } catch (RuntimeException invalid) {
            throw new IllegalArgumentException("invalid sample cursor", invalid);
        }
    }

    public record Boundary(Instant createdAt, UUID id) {}
}
