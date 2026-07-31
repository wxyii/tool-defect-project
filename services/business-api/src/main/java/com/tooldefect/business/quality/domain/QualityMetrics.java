package com.tooldefect.business.quality.domain;

import com.tooldefect.business.shared.domain.DomainViolation;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** 由业务库真实复核/处置记录汇总的质量指标；不包含前端处置规则。 */
public record QualityMetrics(
    Instant windowStart,
    Instant windowEnd,
    double autoPassFailRate,
    double modelOverturnRate,
    long missedDetectionCount,
    long falsePositiveCount,
    List<Reason> maskRevisionReasons,
    long totalSampleCount,
    boolean basedOnFullGroundTruth
) {

    public QualityMetrics {
        Objects.requireNonNull(windowStart);
        Objects.requireNonNull(windowEnd);
        if (!windowStart.isBefore(windowEnd)) {
            throw new DomainViolation("质量指标时间窗口必须是正区间");
        }
        if (!Double.isFinite(autoPassFailRate) || autoPassFailRate < 0 || autoPassFailRate > 1
                || !Double.isFinite(modelOverturnRate) || modelOverturnRate < 0
                || modelOverturnRate > 1) {
            throw new DomainViolation("质量指标比例不在 0 到 1 范围内");
        }
        if (missedDetectionCount < 0 || falsePositiveCount < 0 || totalSampleCount < 0) {
            throw new DomainViolation("质量指标计数不能为负");
        }
        maskRevisionReasons = List.copyOf(maskRevisionReasons);
    }

    public Map<String, Object> toResponse() {
        return Map.of(
            "time_window", Map.of(
                "start", windowStart.toString(),
                "end", windowEnd.toString()
            ),
            "auto_pass_fail_rate", autoPassFailRate,
            "model_overturn_rate", modelOverturnRate,
            "missed_detection_count", missedDetectionCount,
            "false_positive_count", falsePositiveCount,
            "mask_revision_reasons", maskRevisionReasons.stream()
                .map(Reason::toResponse)
                .toList(),
            "total_sample_count", totalSampleCount,
            "based_on_full_ground_truth", basedOnFullGroundTruth
        );
    }

    public record Reason(String reason, long count, double percentage) {
        public Reason {
            if (reason == null || reason.isBlank() || reason.length() > 128) {
                throw new DomainViolation("质量修正原因不合法");
            }
            if (count < 0 || !Double.isFinite(percentage) || percentage < 0 || percentage > 1) {
                throw new DomainViolation("质量修正原因统计不合法");
            }
        }

        private Map<String, Object> toResponse() {
            return Map.of("reason", reason, "count", count, "percentage", percentage);
        }
    }
}
