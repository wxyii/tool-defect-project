package com.tooldefect.business.dataset.domain;

import com.tooldefect.business.shared.domain.DomainViolation;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record CandidateSample(
    UUID candidateId,
    UUID captureId,
    UUID imageId,
    UUID maskImageId,
    String label,
    String split,
    String groupKey,
    String contentSha256,
    UUID sourceReviewRecordId,
    CandidateSampleStatus status,
    Instant addedAt,
    Instant approvedAt,
    UUID approvedBy
) {

    public enum CandidateSampleStatus {
        PENDING,
        APPROVED,
        REJECTED
    }

    public CandidateSample {
        Objects.requireNonNull(candidateId);
        Objects.requireNonNull(captureId);
        Objects.requireNonNull(imageId);
        Objects.requireNonNull(label);
        Objects.requireNonNull(split);
        Objects.requireNonNull(contentSha256);
        if (!contentSha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("内容 SHA-256 格式不合法");
        }
        Objects.requireNonNull(status);
        Objects.requireNonNull(addedAt);
    }

    public CandidateSample approve(UUID approverId, Instant approvedAt) {
        if (status != CandidateSampleStatus.PENDING) {
            throw new DomainViolation("只有待审批状态的样本可以批准");
        }
        return new CandidateSample(
            candidateId, captureId, imageId, maskImageId,
            label, split, groupKey, contentSha256,
            sourceReviewRecordId,
            CandidateSampleStatus.APPROVED, addedAt, approvedAt, approverId
        );
    }

    public CandidateSample reject(UUID approverId, Instant rejectedAt) {
        if (status != CandidateSampleStatus.PENDING) {
            throw new DomainViolation("只有待审批状态的样本可以拒绝");
        }
        return new CandidateSample(
            candidateId, captureId, imageId, maskImageId,
            label, split, groupKey, contentSha256,
            sourceReviewRecordId,
            CandidateSampleStatus.REJECTED, addedAt, rejectedAt, approverId
        );
    }
}
