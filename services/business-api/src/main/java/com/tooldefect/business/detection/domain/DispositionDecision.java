package com.tooldefect.business.detection.domain;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;

import com.tooldefect.business.capture.domain.BusinessDisposition;

public record DispositionDecision(
        BusinessDisposition disposition,
        boolean requiresReview,
        String reasonCode,
        String policyVersion,
        Map<String, Object> policySnapshot,
        Map<String, Object> inputSummary) {

    public DispositionDecision {
        Objects.requireNonNull(disposition);
        if (requiresReview != (disposition == BusinessDisposition.HOLD)) {
            throw new IllegalArgumentException("HOLD 与复核要求必须一致");
        }
        if (reasonCode == null || reasonCode.isBlank()) {
            throw new IllegalArgumentException("处置原因不能为空");
        }
        if (policyVersion == null || policyVersion.isBlank()) {
            throw new IllegalArgumentException("策略版本不能为空");
        }
        policySnapshot = Collections.unmodifiableMap(
            new LinkedHashMap<>(Objects.requireNonNull(policySnapshot))
        );
        inputSummary = Collections.unmodifiableMap(
            new LinkedHashMap<>(Objects.requireNonNull(inputSummary))
        );
    }
}
