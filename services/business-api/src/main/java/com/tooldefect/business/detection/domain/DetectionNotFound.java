package com.tooldefect.business.detection.domain;

public final class DetectionNotFound extends RuntimeException {
    public DetectionNotFound(String message) {
        super(message);
    }
}
