package com.tooldefect.business.sample.infrastructure;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("td.sample-export")
public record SampleProperties(
        boolean enabled,
        String objectBucket,
        String objectPrefix,
        int maximumCandidates,
        long maximumPackageBytes,
        Duration packageRetention,
        Duration ticketTtl) {
    public SampleProperties {
        if (objectBucket == null || !objectBucket.matches("[a-z0-9][a-z0-9.-]{1,62}")
                || !"sample-exports".equals(objectPrefix)
                || maximumCandidates < 1 || maximumCandidates > 100_000
                || maximumPackageBytes < 1 || maximumPackageBytes > 10_737_418_240L
                || packageRetention == null || packageRetention.isNegative()
                || packageRetention.isZero()
                || ticketTtl == null || ticketTtl.isNegative() || ticketTtl.isZero()
                || ticketTtl.compareTo(Duration.ofMinutes(15)) > 0) {
            throw new IllegalArgumentException("R7 样本导出策略不合法");
        }
    }
}
