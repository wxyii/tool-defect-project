package com.tooldefect.business.capture.domain;

import java.util.EnumSet;
import java.util.Map;
import java.util.Set;

import com.tooldefect.business.shared.domain.DomainViolation;

public enum CaptureStatus {
    CREATED,
    UPLOADING,
    READY,
    SUBMITTED,
    PROCESSING,
    REVIEW_PENDING,
    FINALIZED,
    FAILED;

    private static final Map<CaptureStatus, Set<CaptureStatus>> TRANSITIONS = Map.of(
        CREATED, EnumSet.of(UPLOADING, FAILED),
        UPLOADING, EnumSet.of(READY, FAILED),
        READY, EnumSet.of(SUBMITTED),
        SUBMITTED, EnumSet.of(PROCESSING, FAILED),
        PROCESSING, EnumSet.of(REVIEW_PENDING, FINALIZED, FAILED),
        REVIEW_PENDING, EnumSet.of(FINALIZED),
        FAILED, EnumSet.of(SUBMITTED),
        FINALIZED, EnumSet.noneOf(CaptureStatus.class)
    );

    public void requireTransitionTo(CaptureStatus target) {
        if (target != this && !TRANSITIONS.get(this).contains(target)) {
            throw new DomainViolation("非法中央采集状态转换：" + this + " -> " + target);
        }
    }
}
