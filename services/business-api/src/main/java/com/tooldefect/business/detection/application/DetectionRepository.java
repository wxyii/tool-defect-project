package com.tooldefect.business.detection.application;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.tooldefect.business.detection.domain.DispositionDecision;

public interface DetectionRepository {
    AttemptStart startAttempt(
        UUID detectionTaskId,
        UUID attemptId,
        String sourceMessageId,
        String workerId,
        String runtimeVersion,
        String modelSha256,
        String traceId,
        Instant startedAt
    );

    AttemptContext lockAttempt(UUID attemptId);

    void acceptResult(
        AttemptContext context,
        UUID detectionResultId,
        DetectionResultSubmission result,
        String resultSha256,
        DispositionDecision decision,
        UUID dispositionId,
        UUID reviewTaskId,
        List<UUID> regionIds,
        Instant acceptedAt
    );

    void acceptFailure(
        AttemptContext context,
        DetectionFailureSubmission failure,
        String failureSha256,
        int maximumAttempts,
        Instant retryAt,
        DispositionDecision terminalDecision,
        UUID dispositionId,
        UUID reviewTaskId,
        Instant acceptedAt
    );

    record AttemptStart(UUID attemptId, int attemptNumber, boolean replay) {}

    record AttemptContext(
        UUID attemptId,
        UUID detectionTaskId,
        UUID captureId,
        UUID stationId,
        int attemptNumber,
        String attemptStatus,
        String taskStatus,
        String callbackSha256,
        String acceptedResultSha256,
        String expectedModelVersion,
        String expectedModelSha256,
        String captureQuality,
        boolean forcedReview,
        boolean sampledReview
    ) {}
}
