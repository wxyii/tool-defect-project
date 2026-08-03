package com.tooldefect.business.sample.application;

import java.time.Duration;

public record SampleLibrarySettings(
        boolean enabled,
        String objectBucket,
        String objectPrefix,
        int maximumCandidates,
        long maximumPackageBytes,
        Duration packageRetention,
        Duration ticketTtl) {}
