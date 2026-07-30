package com.tooldefect.business.detection.domain;

import java.util.List;
import java.util.Map;
import java.util.Objects;

import com.tooldefect.business.capture.domain.BusinessDisposition;

/** 固定顺序、版本化且安全失败的自动处置规则。 */
public final class DispositionPolicy {
    private static final List<String> RULE_ORDER = List.of(
        "TECHNICAL_INTEGRITY",
        "PREPROCESS_QUALITY",
        "RESULT_CONSISTENCY",
        "CONFIDENCE_GRAY_ZONE",
        "FORCED_REVIEW",
        "SAMPLING",
        "AUTOMATIC_FINALIZATION"
    );

    private final DispositionPolicyConfig config;

    public DispositionPolicy(DispositionPolicyConfig config) {
        this.config = Objects.requireNonNull(config);
    }

    public DispositionDecision decide(DispositionPolicyInput input) {
        Objects.requireNonNull(input);
        Map<String, Object> snapshot = Map.of(
            "policy_version", config.version(),
            "rule_order", RULE_ORDER,
            "gray_low", config.grayLow(),
            "gray_high", config.grayHigh(),
            "high_score_threshold", config.highScoreThreshold(),
            "warning_requires_review", config.warningRequiresReview(),
            "mask_required_for_unqualified",
            config.maskRequiredForUnqualified()
        );
        Map<String, Object> summary = input.summary();

        if (input.technicalFailure()) {
            return hold("TECHNICAL_FAILURE", snapshot, summary);
        }
        if (input.captureQuality() == PreprocessQuality.REJECTED) {
            return hold("CAPTURE_QUALITY_REJECTED", snapshot, summary);
        }
        if (input.preprocessQuality() == PreprocessQuality.REJECTED) {
            return hold("PREPROCESS_REJECTED", snapshot, summary);
        }
        if (input.algorithmOutcome() == AlgorithmOutcome.INCONCLUSIVE) {
            return hold("ALGORITHM_INCONCLUSIVE", snapshot, summary);
        }
        if (config.warningRequiresReview()
                && (input.captureQuality() == PreprocessQuality.WARNING
                    || input.preprocessQuality() == PreprocessQuality.WARNING)) {
            return hold("QUALITY_WARNING", snapshot, summary);
        }
        if (config.maskRequiredForUnqualified()
                && input.algorithmOutcome() == AlgorithmOutcome.UNQUALIFIED
                && (input.regionCount() == 0
                    || !input.maskArtifactPresent())) {
            return hold("EMPTY_MASK_CONTRADICTION", snapshot, summary);
        }
        if (input.algorithmOutcome() == AlgorithmOutcome.QUALIFIED
                && input.maximumRegionScore().isPresent()
                && input.maximumRegionScore().getAsDouble()
                    >= config.highScoreThreshold()) {
            return hold("HIGH_SCORE_REGION_CONTRADICTION", snapshot, summary);
        }
        if (input.conflictingAlgorithms()) {
            return hold("ALGORITHM_CONFLICT", snapshot, summary);
        }
        if (input.confidence().isEmpty()) {
            return hold("CONFIDENCE_MISSING", snapshot, summary);
        }
        double confidence = input.confidence().getAsDouble();
        if (confidence >= config.grayLow() && confidence <= config.grayHigh()) {
            return hold("CONFIDENCE_GRAY_ZONE", snapshot, summary);
        }
        if (input.forcedReview()) {
            return hold("FORCED_REVIEW", snapshot, summary);
        }
        if (input.sampledReview()) {
            return hold("SAMPLED_REVIEW", snapshot, summary);
        }
        BusinessDisposition disposition =
            input.algorithmOutcome() == AlgorithmOutcome.QUALIFIED
                ? BusinessDisposition.PASS
                : BusinessDisposition.FAIL;
        return new DispositionDecision(
            disposition,
            false,
            "AUTO_" + disposition.name(),
            config.version(),
            snapshot,
            summary
        );
    }

    public DispositionDecision technicalFailure(String reasonCode) {
        Map<String, Object> snapshot = Map.of(
            "policy_version", config.version(),
            "rule_order", RULE_ORDER,
            "gray_low", config.grayLow(),
            "gray_high", config.grayHigh(),
            "high_score_threshold", config.highScoreThreshold(),
            "warning_requires_review", config.warningRequiresReview(),
            "mask_required_for_unqualified",
            config.maskRequiredForUnqualified()
        );
        Map<String, Object> summary = Map.of(
            "technical_failure", true,
            "failure_reason", Objects.requireNonNull(reasonCode)
        );
        return hold(reasonCode, snapshot, summary);
    }

    private DispositionDecision hold(
            String reason,
            Map<String, Object> snapshot,
            Map<String, Object> summary) {
        return new DispositionDecision(
            BusinessDisposition.HOLD,
            true,
            reason,
            config.version(),
            snapshot,
            summary
        );
    }
}
