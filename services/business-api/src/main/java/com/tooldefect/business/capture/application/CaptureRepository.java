package com.tooldefect.business.capture.application;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

public interface CaptureRepository {
    void insertCapture(CaptureRegistration registration, String requestSha256);

    void attachImageMetadata(
        UUID imageId,
        CaptureImageRegistration image
    );

    boolean allImagesAvailable(UUID captureId);

    void markReady(UUID captureId);

    SubmissionContext lockReadySubmission(UUID captureId, UUID stationId);

    void insertDetectionTask(UUID detectionTaskId, SubmissionContext context);

    void markSubmitted(UUID captureId);

    Optional<CaptureStatusView> findStatus(UUID captureId, UUID stationId);

    void updateHeartbeat(
        UUID deviceId,
        UUID stationId,
        String agentVersion,
        Instant reportedAt,
        Map<String, Object> snapshot
    );

    record SubmissionContext(
        UUID captureId,
        UUID stationId,
        UUID recipeId,
        Instant capturedAt,
        UUID pipelineId,
        String pipelineVersion,
        String configSha256,
        String preprocessorVersion,
        String algorithmVersion,
        String modelVersion,
        String modelSha256,
        List<ImageReference> images) {

        public SubmissionContext {
            images = List.copyOf(images);
        }
    }

    record ImageReference(
        UUID imageId,
        String imageRole,
        String kind,
        String bucket,
        String objectKey,
        String objectVersion,
        String sha256,
        long sizeBytes,
        String mediaType,
        int width,
        int height) {}
}
