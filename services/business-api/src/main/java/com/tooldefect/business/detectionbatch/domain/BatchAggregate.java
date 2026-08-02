package com.tooldefect.business.detectionbatch.domain;

import java.util.List;
import java.util.Objects;

/** 可由逐项事实完全重建的批次投影。 */
public record BatchAggregate(Status status, Counts counts) {
    public static BatchAggregate rebuild(List<BatchItemSnapshot> items) {
        Objects.requireNonNull(items, "items");
        int completed = 0;
        int defectSuspected = 0;
        int normal = 0;
        int inconclusive = 0;
        int qualityRejected = 0;
        int technicalFailed = 0;

        for (BatchItemSnapshot item : List.copyOf(items)) {
            Objects.requireNonNull(item, "item");
            if (item.status().terminal()) {
                completed++;
            }
            if (item.status() == BatchItemSnapshot.Status.QUALITY_REJECTED) {
                qualityRejected++;
            } else if (item.status() == BatchItemSnapshot.Status.FAILED) {
                technicalFailed++;
            } else if (item.status() == BatchItemSnapshot.Status.COMPLETED) {
                switch (item.outcome()) {
                    case QUALIFIED -> normal++;
                    case UNQUALIFIED -> defectSuspected++;
                    case INCONCLUSIVE -> inconclusive++;
                }
            }
        }

        Counts counts = new Counts(
            items.size(), completed, defectSuspected, normal, inconclusive,
            qualityRejected, technicalFailed
        );
        Status status;
        if (items.isEmpty()) {
            status = Status.FAILED;
        } else if (completed < items.size()) {
            status = Status.PROCESSING;
        } else if (technicalFailed == items.size()) {
            status = Status.FAILED;
        } else if (technicalFailed > 0 || qualityRejected > 0) {
            status = Status.PARTIALLY_COMPLETED;
        } else {
            status = Status.COMPLETED;
        }
        return new BatchAggregate(status, counts);
    }

    public enum Status {
        PROCESSING,
        COMPLETED,
        PARTIALLY_COMPLETED,
        FAILED
    }

    public record Counts(
        int total,
        int completed,
        int defectSuspected,
        int normal,
        int inconclusive,
        int qualityRejected,
        int technicalFailed
    ) {
        public Counts {
            if (total < 0 || completed < 0 || defectSuspected < 0 || normal < 0
                    || inconclusive < 0 || qualityRejected < 0
                    || technicalFailed < 0 || completed > total
                    || defectSuspected + normal + inconclusive
                        + qualityRejected + technicalFailed > total) {
                throw new IllegalArgumentException("批次计数不合法");
            }
        }
    }
}
