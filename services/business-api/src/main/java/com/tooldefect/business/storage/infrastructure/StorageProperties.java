package com.tooldefect.business.storage.infrastructure;

import java.net.URI;
import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties("td.storage")
public record StorageProperties(
        boolean enabled,
        URI endpoint,
        URI publicEndpoint,
        String region,
        String accessKey,
        String secretKey,
        boolean pathStyleAccess,
        boolean requireTls,
        String rawBucket,
        Duration uploadTtl,
        Duration readTtl,
        long maximumPixels,
        long maximumDecodedBytes,
        long maximumObjectBytes) {
}
