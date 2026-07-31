package com.tooldefect.business.quality.application;

import com.tooldefect.business.quality.domain.QualityMetrics;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

@Service
public class QualityQueryService {

    private final QualityMetricsRepository metrics;

    public QualityQueryService(QualityMetricsRepository metrics) {
        this.metrics = Objects.requireNonNull(metrics);
    }

    @Transactional(readOnly = true)
    public QualityMetrics getMetrics(
            Instant windowStart, Instant windowEnd, UUID modelVersionId) {
        return metrics.summarize(windowStart, windowEnd, modelVersionId);
    }

    public Map<String, Object> getMetricsResponse(
            Instant windowStart, Instant windowEnd, UUID modelVersionId) {
        return getMetrics(windowStart, windowEnd, modelVersionId).toResponse();
    }
}
