package com.tooldefect.business.detectionbatch.domain;

import java.util.Objects;

/** 聚合重建只依赖持久化的逐项终态，不接受前端提供的计数。 */
public record BatchItemSnapshot(Status status, Outcome outcome) {
    public BatchItemSnapshot {
        Objects.requireNonNull(status, "status");
        if (status == Status.COMPLETED && outcome == null) {
            throw new IllegalArgumentException("完成项必须有算法结论");
        }
        if (status != Status.COMPLETED && outcome != null) {
            throw new IllegalArgumentException("非完成项不得伪造算法结论");
        }
    }

    public enum Status {
        PENDING_UPLOAD,
        UPLOADING,
        READY,
        QUEUED,
        PROCESSING,
        COMPLETED,
        QUALITY_REJECTED,
        FAILED,
        CANCELLED;

        public boolean terminal() {
            return this == COMPLETED || this == QUALITY_REJECTED
                || this == FAILED || this == CANCELLED;
        }
    }

    public enum Outcome {
        QUALIFIED,
        UNQUALIFIED,
        INCONCLUSIVE
    }
}
