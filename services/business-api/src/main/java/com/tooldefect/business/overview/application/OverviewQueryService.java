package com.tooldefect.business.overview.application;

import java.time.Instant;
import java.util.Map;
import java.util.Objects;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OverviewQueryService {
    private final OverviewQueryRepository overview;

    public OverviewQueryService(OverviewQueryRepository overview) {
        this.overview = Objects.requireNonNull(overview);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> getOverview(
            String actorId,
            Instant generatedAt,
            Instant currentStart,
            Instant currentEnd,
            Instant previousStart,
            Instant previousEnd,
            Instant heartbeatCutoff,
            long heartbeatFreshnessSeconds,
            String timezone) {
        return overview.summarize(
            actorId,
            generatedAt,
            currentStart,
            currentEnd,
            previousStart,
            previousEnd,
            heartbeatCutoff,
            heartbeatFreshnessSeconds,
            timezone
        );
    }
}
