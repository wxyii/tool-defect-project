package com.tooldefect.business.storage.application;

import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

import com.tooldefect.business.shared.domain.DomainViolation;

public final class ObjectKeyPolicy {
    private static final Set<String> ROLES = Set.of("primary", "side", "top", "auxiliary");

    public String rawKey(
            LocalDate date,
            UUID stationId,
            UUID captureId,
            String imageRole,
            String sha256,
            String extension) {
        String role = imageRole.toLowerCase(Locale.ROOT);
        if (!ROLES.contains(role)) {
            throw new DomainViolation("未知图片角色");
        }
        if (sha256 == null || !sha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("SHA-256 不合法");
        }
        String ext = extension.toLowerCase(Locale.ROOT);
        if (!ext.matches("[a-z0-9]+")) {
            throw new DomainViolation("扩展名不合法");
        }
        return String.format(
            Locale.ROOT,
            "raw/%04d/%02d/%02d/%s/%s/%s-%s.%s",
            date.getYear(),
            date.getMonthValue(),
            date.getDayOfMonth(),
            stationId,
            captureId,
            role,
            sha256.substring(0, 16),
            ext
        );
    }

    public String reviewMaskKey(
            LocalDate date,
            UUID reviewTaskId,
            UUID imageId,
            String sha256) {
        if (sha256 == null || !sha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("SHA-256 不合法");
        }
        return String.format(
            Locale.ROOT,
            "review/%04d/%02d/%02d/%s/%s-%s.png",
            date.getYear(),
            date.getMonthValue(),
            date.getDayOfMonth(),
            reviewTaskId,
            imageId,
            sha256.substring(0, 16)
        );
    }
}
