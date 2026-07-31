package com.tooldefect.business.quality.application;

import com.tooldefect.business.quality.domain.QualityMetrics;

import java.time.Instant;
import java.util.UUID;

public interface QualityMetricsRepository {

    QualityMetrics summarize(Instant windowStart, Instant windowEnd, UUID modelVersionId);
}
