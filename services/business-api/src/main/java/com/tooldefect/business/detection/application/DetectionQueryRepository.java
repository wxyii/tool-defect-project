package com.tooldefect.business.detection.application;

import java.util.Map;
import java.util.UUID;

public interface DetectionQueryRepository {
    Map<String, Object> list(
        String actorId,
        String cursor,
        int pageSize,
        String businessDisposition,
        String algorithmOutcome,
        String modelVersion
    );

    Map<String, Object> detail(String actorId, UUID detectionTaskId);

    Map<String, Object> detailByCapture(
        String actorId,
        UUID captureId,
        String permission
    );
}
