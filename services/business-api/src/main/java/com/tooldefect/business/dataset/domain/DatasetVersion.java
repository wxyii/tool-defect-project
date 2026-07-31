package com.tooldefect.business.dataset.domain;

import com.tooldefect.business.shared.domain.DomainViolation;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record DatasetVersion(
    UUID datasetVersionId,
    UUID datasetId,
    String version,
    UUID parentVersionId,
    UUID candidateManifestId,
    String purpose,
    String manifestObjectKey,
    String manifestObjectBucket,
    String manifestSha256,
    int sampleCount,
    String stratificationJson,
    DatasetVersionState state,
    UUID approvedBy,
    Instant createdAt,
    Instant approvedAt,
    int recordVersion
) {

    public DatasetVersion {
        Objects.requireNonNull(datasetVersionId);
        Objects.requireNonNull(datasetId);
        if (version == null || !version.matches("[A-Za-z0-9][A-Za-z0-9._/-]*")) {
            throw new DomainViolation("数据集版本号不符合 v1 契约");
        }
        if (purpose != null && (purpose.isBlank() || purpose.length() > 256)) {
            throw new DomainViolation("数据集版本用途不能为空且不能超过 256 字符");
        }
        if (sampleCount < 0) {
            throw new DomainViolation("样本数不能为负");
        }
        Objects.requireNonNull(state);
        Objects.requireNonNull(createdAt);
    }

    public DatasetVersion withState(DatasetVersionState newState) {
        if (this.state == DatasetVersionState.FROZEN && newState != DatasetVersionState.FROZEN) {
            throw new DomainViolation("已冻结的数据集版本不可更改状态");
        }
        return new DatasetVersion(
            datasetVersionId, datasetId, version, parentVersionId,
            candidateManifestId, purpose,
            manifestObjectKey, manifestObjectBucket, manifestSha256,
            sampleCount, stratificationJson, newState, approvedBy,
            createdAt, approvedAt, recordVersion + 1
        );
    }

    public DatasetVersion withApproval(UUID approverId, Instant approvedAt) {
        if (this.state != DatasetVersionState.VALIDATING) {
            throw new DomainViolation("只能审批处于验证中状态的数据集版本");
        }
        return new DatasetVersion(
            datasetVersionId, datasetId, version, parentVersionId,
            candidateManifestId, purpose,
            manifestObjectKey, manifestObjectBucket, manifestSha256,
            sampleCount, stratificationJson, DatasetVersionState.FROZEN,
            approverId, createdAt, approvedAt, recordVersion + 1
        );
    }
}
