package com.tooldefect.business.detection.domain;

import com.tooldefect.business.shared.domain.DomainViolation;

public record DispositionPolicyConfig(
        String version,
        double grayLow,
        double grayHigh,
        double highScoreThreshold,
        boolean warningRequiresReview,
        boolean maskRequiredForUnqualified) {

    public DispositionPolicyConfig {
        if (version == null || version.isBlank() || version.length() > 64) {
            throw new DomainViolation("处置策略版本不合法");
        }
        requireProbability(grayLow, "grayLow");
        requireProbability(grayHigh, "grayHigh");
        requireProbability(highScoreThreshold, "highScoreThreshold");
        if (grayLow > grayHigh) {
            throw new DomainViolation("灰区下界不能高于上界");
        }
    }

    private static void requireProbability(double value, String field) {
        if (!Double.isFinite(value) || value < 0 || value > 1) {
            throw new DomainViolation(field + " 必须位于 0 到 1");
        }
    }
}
