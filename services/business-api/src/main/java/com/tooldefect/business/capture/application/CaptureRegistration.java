package com.tooldefect.business.capture.application;

import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record CaptureRegistration(
        UUID captureId,
        UUID stationId,
        UUID recipeId,
        String triggerId,
        long clientSequence,
        Instant capturedAt,
        String triggerSource,
        String qualityStatus,
        List<String> qualityWarnings,
        List<CaptureImageRegistration> images) {

    public CaptureRegistration {
        Objects.requireNonNull(captureId);
        Objects.requireNonNull(stationId);
        Objects.requireNonNull(recipeId);
        Objects.requireNonNull(capturedAt);
        qualityWarnings = List.copyOf(qualityWarnings);
        images = List.copyOf(images);
        if (images.isEmpty()) {
            throw new IllegalArgumentException("采集至少包含一张图片");
        }
    }
}
