package com.tooldefect.business.detectionbatch.application;

import java.time.Duration;
import java.util.List;

public record ManualDetectionSettings(boolean enabled, String objectBucket, String objectPrefix,
        int maximumItemsPerBatch, long maximumObjectBytes, List<String> allowedMediaTypes,
        Duration uploadTtl, Duration readTtl, Duration orphanRetention, int cleanupBatchSize) {
    public ManualDetectionSettings {
        allowedMediaTypes = List.copyOf(allowedMediaTypes);
    }
}
