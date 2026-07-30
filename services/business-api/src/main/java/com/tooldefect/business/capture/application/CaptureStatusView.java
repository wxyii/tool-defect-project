package com.tooldefect.business.capture.application;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

public record CaptureStatusView(
        UUID captureId,
        String captureStatus,
        String businessDisposition,
        UUID detectionTaskId,
        String taskStatus,
        String algorithmOutcome,
        Double confidence,
        String modelVersion,
        String reviewStatus) {

    public Map<String, Object> toContract() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("capture_id", captureId.toString());
        result.put("capture_status", captureStatus);
        result.put("business_disposition", businessDisposition);
        if (detectionTaskId != null) {
            Map<String, Object> detection = new LinkedHashMap<>();
            detection.put("detection_task_id", detectionTaskId.toString());
            detection.put("task_status", taskStatus);
            detection.put("algorithm_outcome", algorithmOutcome);
            detection.put("confidence", confidence);
            detection.put("model_version", modelVersion);
            result.put("detection", Collections.unmodifiableMap(detection));
        }
        if (reviewStatus != null) {
            result.put("review", Map.of("status", reviewStatus));
        }
        result.put(
            "poll_after_ms",
            switch (captureStatus) {
                case "FINALIZED", "FAILED" -> 0;
                case "REVIEW_PENDING" -> 3000;
                default -> 500;
            }
        );
        return Collections.unmodifiableMap(result);
    }
}
