package com.tooldefect.business.capture.application;

import java.util.Objects;

public record CaptureImageRegistration(
        String clientImageId,
        String imageRole,
        String fileName,
        String mediaType,
        long sizeBytes,
        String sha256,
        int width,
        int height) {

    public CaptureImageRegistration {
        Objects.requireNonNull(clientImageId);
        Objects.requireNonNull(imageRole);
        Objects.requireNonNull(fileName);
        Objects.requireNonNull(mediaType);
        Objects.requireNonNull(sha256);
    }

    public String extension() {
        int separator = fileName.lastIndexOf('.');
        if (separator < 0 || separator == fileName.length() - 1) {
            return switch (mediaType) {
                case "image/png" -> "png";
                case "image/jpeg" -> "jpg";
                default -> throw new IllegalArgumentException("媒体类型没有安全扩展名");
            };
        }
        return fileName.substring(separator + 1).toLowerCase(java.util.Locale.ROOT);
    }
}
