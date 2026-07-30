package com.tooldefect.business.detection.domain;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.OptionalDouble;
import java.util.Collections;

import com.tooldefect.business.shared.domain.DomainViolation;

public record DispositionPolicyInput(
        boolean technicalFailure,
        PreprocessQuality captureQuality,
        PreprocessQuality preprocessQuality,
        AlgorithmOutcome algorithmOutcome,
        OptionalDouble confidence,
        int regionCount,
        OptionalDouble maximumRegionScore,
        boolean maskArtifactPresent,
        boolean conflictingAlgorithms,
        boolean forcedReview,
        boolean sampledReview) {

    public DispositionPolicyInput {
        Objects.requireNonNull(captureQuality);
        Objects.requireNonNull(preprocessQuality);
        Objects.requireNonNull(algorithmOutcome);
        Objects.requireNonNull(confidence);
        Objects.requireNonNull(maximumRegionScore);
        if (regionCount < 0) {
            throw new DomainViolation("区域数量不能为负数");
        }
        confidence.ifPresent(value -> requireProbability(value, "confidence"));
        maximumRegionScore.ifPresent(
            value -> requireProbability(value, "maximumRegionScore")
        );
    }

    public Map<String, Object> summary() {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("technical_failure", technicalFailure);
        value.put("capture_quality", captureQuality.name());
        value.put("preprocess_quality", preprocessQuality.name());
        value.put("algorithm_outcome", algorithmOutcome.name());
        value.put(
            "confidence",
            confidence.isPresent() ? confidence.getAsDouble() : null
        );
        value.put("region_count", regionCount);
        value.put(
            "maximum_region_score",
            maximumRegionScore.isPresent()
                ? maximumRegionScore.getAsDouble()
                : null
        );
        value.put("mask_artifact_present", maskArtifactPresent);
        value.put("conflicting_algorithms", conflictingAlgorithms);
        value.put("forced_review", forcedReview);
        value.put("sampled_review", sampledReview);
        return Collections.unmodifiableMap(value);
    }

    private static void requireProbability(double value, String field) {
        if (!Double.isFinite(value) || value < 0 || value > 1) {
            throw new DomainViolation(field + " 必须位于 0 到 1");
        }
    }
}
