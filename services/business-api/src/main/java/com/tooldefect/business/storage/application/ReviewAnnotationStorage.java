package com.tooldefect.business.storage.application;

import java.net.URI;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

public interface ReviewAnnotationStorage {
    UploadTicket issue(
        UUID imageId,
        UUID reviewTaskId,
        UUID captureId,
        long sizeBytes,
        String sha256,
        int width,
        int height
    );

    ConfirmedAnnotation confirm(
        UUID reviewTaskId,
        UUID imageId,
        long sizeBytes,
        String sha256,
        String uploadReceipt
    );

    record UploadTicket(
        UUID imageId,
        String method,
        URI url,
        Map<String, String> headers,
        Instant expiresAt
    ) {
    }

    record ConfirmedAnnotation(
        UUID imageId,
        String sha256
    ) {
    }
}
