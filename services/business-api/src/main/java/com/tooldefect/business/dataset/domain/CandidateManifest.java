package com.tooldefect.business.dataset.domain;

import com.tooldefect.business.shared.domain.DomainViolation;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

/** 已登记的候选清单对象；只有独立审批后的对象可以创建数据集版本。 */
public record CandidateManifest(
    UUID candidateManifestId,
    UUID datasetId,
    String manifestBucket,
    String manifestObjectKey,
    String manifestSha256,
    int sampleCount,
    ApprovalState approvalState,
    UUID approvedBy,
    Instant approvedAt,
    Instant createdAt
) {

    public enum ApprovalState {
        REGISTERED,
        APPROVED,
        REJECTED
    }

    public CandidateManifest {
        Objects.requireNonNull(candidateManifestId);
        Objects.requireNonNull(datasetId);
        requireText(manifestBucket, "manifestBucket");
        requireText(manifestObjectKey, "manifestObjectKey");
        if (manifestSha256 == null || !manifestSha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("候选清单 SHA-256 格式不合法");
        }
        if (sampleCount < 0) {
            throw new DomainViolation("候选清单样本数不能为负");
        }
        Objects.requireNonNull(approvalState);
        Objects.requireNonNull(createdAt);
        if (approvalState == ApprovalState.APPROVED
                && (approvedBy == null || approvedAt == null)) {
            throw new DomainViolation("已批准候选清单必须有审批人和审批时间");
        }
        if (approvalState != ApprovalState.APPROVED
                && (approvedBy != null || approvedAt != null)) {
            throw new DomainViolation("未批准候选清单不能携带审批事实");
        }
    }

    public CandidateManifest approve(UUID approverId, Instant approvalTime) {
        if (approvalState != ApprovalState.REGISTERED) {
            throw new DomainViolation("只有已登记候选清单可以批准");
        }
        return new CandidateManifest(
            candidateManifestId,
            datasetId,
            manifestBucket,
            manifestObjectKey,
            manifestSha256,
            sampleCount,
            ApprovalState.APPROVED,
            Objects.requireNonNull(approverId),
            Objects.requireNonNull(approvalTime),
            createdAt
        );
    }

    public CandidateManifest reject() {
        if (approvalState != ApprovalState.REGISTERED) {
            throw new DomainViolation("只有已登记候选清单可以驳回");
        }
        return new CandidateManifest(
            candidateManifestId,
            datasetId,
            manifestBucket,
            manifestObjectKey,
            manifestSha256,
            sampleCount,
            ApprovalState.REJECTED,
            null,
            null,
            createdAt
        );
    }

    private static void requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new DomainViolation(field + " 不能为空");
        }
    }
}
