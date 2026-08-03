package com.tooldefect.business.detectionbatch.infrastructure;

import java.time.Duration;
import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("td.manual-detection")
public record ManualDetectionProperties(
        boolean enabled,
        String objectBucket,
        String objectPrefix,
        int maximumItemsPerBatch,
        long maximumObjectBytes,
        List<String> allowedMediaTypes,
        Duration uploadTtl,
        Duration readTtl,
        Duration orphanRetention,
        int cleanupBatchSize) {
    public ManualDetectionProperties {
        allowedMediaTypes = List.copyOf(allowedMediaTypes);
        if (objectBucket == null || !objectBucket.matches("[a-z0-9][a-z0-9.-]{1,62}")
                || !"manual-originals".equals(objectPrefix)
                || maximumItemsPerBatch < 10
                || maximumObjectBytes <= 0
                || !allowedMediaTypes.equals(List.of("image/jpeg", "image/png"))
                || uploadTtl.isNegative() || uploadTtl.isZero()
                || readTtl.isNegative() || readTtl.isZero()
                || orphanRetention.isNegative() || orphanRetention.isZero()
                || cleanupBatchSize <= 0) {
            throw new IllegalArgumentException("手工检测对象存储策略不合法");
        }
    }
}
