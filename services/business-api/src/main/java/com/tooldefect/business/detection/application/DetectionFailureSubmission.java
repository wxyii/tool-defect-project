package com.tooldefect.business.detection.application;

import java.time.Instant;
import java.util.Map;
import java.util.Objects;

public record DetectionFailureSubmission(
        String errorCode,
        String stage,
        boolean retryable,
        String message,
        Instant occurredAt,
        Map<String, Object> raw) {

    public DetectionFailureSubmission {
        Objects.requireNonNull(errorCode);
        Objects.requireNonNull(stage);
        Objects.requireNonNull(message);
        Objects.requireNonNull(occurredAt);
        raw = Map.copyOf(raw);
    }
}
