package com.tooldefect.business.review.application;

import java.time.Instant;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

import com.tooldefect.business.shared.domain.DomainViolation;

public record ReviewSubmission(
        String decision,
        String reasonCode,
        String comment,
        List<String> defectTypeCodes,
        UUID annotationImageId,
        Instant clientSubmittedAt) {
    private static final Set<String> DECISIONS = Set.of(
        "PASS", "FAIL", "HOLD"
    );

    public ReviewSubmission {
        if (!DECISIONS.contains(decision)) {
            throw new DomainViolation("复核生产结论不合法");
        }
        if (reasonCode == null
                || reasonCode.isBlank()
                || reasonCode.length() > 64) {
            throw new DomainViolation("复核原因码不合法");
        }
        comment = comment == null ? "" : comment;
        if (comment.length() > 2000) {
            throw new DomainViolation("复核说明超过长度限制");
        }
        Objects.requireNonNull(defectTypeCodes);
        if (defectTypeCodes.size() > 32
                || new LinkedHashSet<>(defectTypeCodes).size()
                    != defectTypeCodes.size()) {
            throw new DomainViolation("缺陷类型重复或超过数量限制");
        }
        for (String code : defectTypeCodes) {
            if (code == null || code.isBlank() || code.length() > 64) {
                throw new DomainViolation("缺陷类型编码不合法");
            }
        }
        defectTypeCodes = List.copyOf(defectTypeCodes);
        Objects.requireNonNull(clientSubmittedAt);
    }
}
