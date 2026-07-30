package com.tooldefect.business.detection.domain;

import java.util.Map;
import java.util.Objects;
import java.util.OptionalDouble;
import java.util.UUID;

import com.tooldefect.business.shared.domain.DomainViolation;

public record DetectionResult(
        UUID detectionResultId,
        UUID detectionTaskId,
        UUID acceptedAttemptId,
        String schemaVersion,
        AlgorithmOutcome algorithmOutcome,
        OptionalDouble confidence,
        Map<String, Double> classProbabilities,
        String resultSha256) {

    public DetectionResult {
        Objects.requireNonNull(detectionResultId);
        Objects.requireNonNull(detectionTaskId);
        Objects.requireNonNull(acceptedAttemptId);
        if (schemaVersion == null || schemaVersion.isBlank()) {
            throw new DomainViolation("结果模式版本不能为空");
        }
        Objects.requireNonNull(algorithmOutcome);
        Objects.requireNonNull(confidence);
        classProbabilities = Map.copyOf(Objects.requireNonNull(classProbabilities));
        if (confidence.isPresent()) {
            requireProbability(confidence.getAsDouble(), "confidence");
        }
        double sum = 0.0;
        for (var entry : classProbabilities.entrySet()) {
            requireProbability(entry.getValue(), entry.getKey());
            sum += entry.getValue();
        }
        if (!classProbabilities.isEmpty() && Math.abs(sum - 1.0) > 1e-6) {
            throw new DomainViolation("分类概率和必须为 1");
        }
        if (resultSha256 == null || !resultSha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("结果 SHA-256 不合法");
        }
    }

    private static void requireProbability(double value, String field) {
        if (!Double.isFinite(value) || value < 0 || value > 1) {
            throw new DomainViolation(field + " 必须位于 0 到 1");
        }
    }
}
