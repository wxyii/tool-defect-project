package com.tooldefect.business.storage.application;

import java.time.LocalDate;
import java.util.Locale;
import java.util.UUID;

import com.tooldefect.business.shared.domain.DomainViolation;

public final class ObjectKeyPolicy {
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
