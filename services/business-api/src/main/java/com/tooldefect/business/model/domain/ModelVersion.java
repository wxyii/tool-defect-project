package com.tooldefect.business.model.domain;

import com.tooldefect.business.shared.domain.DomainViolation;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record ModelVersion(
    UUID modelVersionId,
    UUID modelId,
    int version,
    String sourceKind,
    UUID modelUploadId,
    String externalSourceSnapshotJson,
    String registryName,
    String registryVersion,
    String artifactBucket,
    String artifactObjectKey,
    String artifactSha256,
    String sbomSha256,
    String signatureKeyId,
    String inputSpecJson,
    String outputSpecJson,
    String evaluationSummaryJson,
    String evaluationReportSha256,
    String thresholdGateSha256,
    ModelApprovalState approvalState,
    UUID registeredBy,
    UUID validatedBy,
    Instant validatedAt,
    UUID approvedBy,
    Instant approvedAt,
    Instant createdAt
) {

    public ModelVersion {
        Objects.requireNonNull(modelVersionId);
        Objects.requireNonNull(modelId);
        if (version <= 0) {
            throw new DomainViolation("模型版本号必须为正整数");
        }
        if (!"EXTERNAL_UPLOAD".equals(sourceKind)) {
            throw new DomainViolation("模型版本只能使用第二版外部上传来源");
        }
        Objects.requireNonNull(modelUploadId);
        Objects.requireNonNull(externalSourceSnapshotJson);
        if (externalSourceSnapshotJson.isBlank()) {
            throw new DomainViolation("外部来源快照不能为空");
        }
        Objects.requireNonNull(artifactSha256);
        if (!artifactSha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("artifact_sha256 必须是合法 SHA-256 十六进制");
        }
        if ((registryName == null) != (registryVersion == null)) {
            throw new DomainViolation("registry_name 和 registry_version 必须同时存在或同时缺失");
        }
        if (registryName != null
                && (registryName.isBlank() || registryName.length() > 256)) {
            throw new DomainViolation("registry_name 不能为空且不能超过 256 字符");
        }
        if (registryVersion != null
                && (registryVersion.isBlank() || registryVersion.length() > 128)) {
            throw new DomainViolation("registry_version 不能为空且不能超过 128 字符");
        }
        Objects.requireNonNull(artifactBucket);
        if (artifactBucket.isBlank() || artifactBucket.length() > 128) {
            throw new DomainViolation("artifact_bucket 不能为空且不能超过 128 字符");
        }
        Objects.requireNonNull(artifactObjectKey);
        if (artifactObjectKey.isBlank()
                || artifactObjectKey.length() > 1024
                || artifactObjectKey.startsWith("/")
                || artifactObjectKey.contains("..")) {
            throw new DomainViolation("artifact_object_key 不能为空且不能越界");
        }
        Objects.requireNonNull(inputSpecJson);
        Objects.requireNonNull(outputSpecJson);
        Objects.requireNonNull(evaluationSummaryJson);

        boolean legacyWithoutSupplyChainEvidence = sbomSha256 == null
                && signatureKeyId == null
                && evaluationReportSha256 == null
                && thresholdGateSha256 == null
                && registeredBy == null;
        if (!legacyWithoutSupplyChainEvidence) {
            Objects.requireNonNull(registeredBy);
            Objects.requireNonNull(sbomSha256);
            if (!sbomSha256.matches("[0-9a-f]{64}")) {
                throw new DomainViolation("sbom_sha256 必须是合法 SHA-256 十六进制");
            }
            Objects.requireNonNull(signatureKeyId);
            if (signatureKeyId.isBlank() || signatureKeyId.length() > 256) {
                throw new DomainViolation("signature_key_id 不能为空且不能超过 256 字符");
            }
            Objects.requireNonNull(evaluationReportSha256);
            if (!evaluationReportSha256.matches("[0-9a-f]{64}")) {
                throw new DomainViolation("evaluation_report_sha256 必须是合法 SHA-256 十六进制");
            }
            Objects.requireNonNull(thresholdGateSha256);
            if (!thresholdGateSha256.matches("[0-9a-f]{64}")) {
                throw new DomainViolation("threshold_gate_sha256 必须是合法 SHA-256 十六进制");
            }
        }
        Objects.requireNonNull(approvalState);
        if ((validatedBy == null) != (validatedAt == null)) {
            throw new DomainViolation("验证审批人和时间必须成对存在");
        }
        if ((approvedBy == null) != (approvedAt == null)) {
            throw new DomainViolation("发布审批人和时间必须成对存在");
        }
        if (approvedBy != null && (validatedBy == null || approvedBy.equals(validatedBy))) {
            throw new DomainViolation("最终发布审批必须有不同于验证审批人的独立审批人");
        }
        Objects.requireNonNull(createdAt);
    }

    /**
     * V8 不会猜测补写历史记录的供应链字段；这类记录可以被读取和审计，
     * 但不能被审批、部署或作为回滚目标。
     */
    public boolean hasCompleteSupplyChainEvidence() {
        return "EXTERNAL_UPLOAD".equals(sourceKind)
                && modelUploadId != null
                && externalSourceSnapshotJson != null
                && registryName != null
                && registryVersion != null
                && registeredBy != null
                && sbomSha256 != null
                && signatureKeyId != null
                && evaluationReportSha256 != null
                && thresholdGateSha256 != null;
    }

    private void requireCompleteSupplyChainEvidence() {
        if (!hasCompleteSupplyChainEvidence()) {
            throw new DomainViolation(
                "历史模型版本缺少供应链证据，当前只能 HOLD，禁止审批或部署"
            );
        }
    }

    public ModelVersion withValidation(UUID approverId, Instant at) {
        if (approvalState != ModelApprovalState.CANDIDATE) {
            throw new DomainViolation("只有候选模型可以进入验证通过状态");
        }
        requireCompleteSupplyChainEvidence();
        if (approverId == null || approverId.equals(registeredBy)) {
            throw new DomainViolation("模型登记人与验证审批人不能为同一人");
        }
        return new ModelVersion(
            modelVersionId, modelId, version, sourceKind, modelUploadId,
            externalSourceSnapshotJson, registryName, registryVersion, artifactBucket,
            artifactObjectKey, artifactSha256, sbomSha256, signatureKeyId,
            inputSpecJson, outputSpecJson, evaluationSummaryJson,
            evaluationReportSha256, thresholdGateSha256, ModelApprovalState.VALIDATED,
            registeredBy, approverId, at, approvedBy, approvedAt, createdAt
        );
    }

    public ModelVersion withFinalApproval(UUID approverId, Instant at) {
        if (approvalState != ModelApprovalState.VALIDATED) {
            throw new DomainViolation("只有通过验证的模型可以进入批准状态");
        }
        requireCompleteSupplyChainEvidence();
        if (approverId == null || approverId.equals(registeredBy) || approverId.equals(validatedBy)) {
            throw new DomainViolation("模型发布审批人必须独立于登记人与验证审批人");
        }
        return new ModelVersion(
            modelVersionId, modelId, version, sourceKind, modelUploadId,
            externalSourceSnapshotJson, registryName, registryVersion, artifactBucket,
            artifactObjectKey, artifactSha256, sbomSha256, signatureKeyId,
            inputSpecJson, outputSpecJson, evaluationSummaryJson,
            evaluationReportSha256, thresholdGateSha256, ModelApprovalState.APPROVED,
            registeredBy, validatedBy, validatedAt, approverId, at, createdAt
        );
    }

    public ModelVersion withRejection() {
        if (approvalState != ModelApprovalState.CANDIDATE
                && approvalState != ModelApprovalState.VALIDATED) {
            throw new DomainViolation("只有候选或已验证模型可以被拒绝");
        }
        requireCompleteSupplyChainEvidence();
        return new ModelVersion(
            modelVersionId, modelId, version, sourceKind, modelUploadId,
            externalSourceSnapshotJson, registryName, registryVersion, artifactBucket,
            artifactObjectKey, artifactSha256, sbomSha256, signatureKeyId,
            inputSpecJson, outputSpecJson, evaluationSummaryJson,
            evaluationReportSha256, thresholdGateSha256, ModelApprovalState.REJECTED,
            registeredBy, validatedBy, validatedAt, approvedBy, approvedAt, createdAt
        );
    }
}
