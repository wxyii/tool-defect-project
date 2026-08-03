package com.tooldefect.business.detectionbatch.application;

import java.util.UUID;

public interface ProductionDetectionRepository {
    Acceptance create(UUID captureId, String deviceSubject, Image image,
                      String idempotencyKey);

    record Image(String bucket, String objectKey, String objectVersion,
                 String sha256, long sizeBytes, String mediaType,
                 int width, int height) {}
    record Acceptance(UUID captureId, UUID batchId, UUID batchItemId,
                      UUID detectionTaskId, String status, Image image) {}
}
