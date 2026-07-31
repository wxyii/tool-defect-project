package com.tooldefect.business.deployment.domain;

import com.tooldefect.business.shared.domain.DomainViolation;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record ModelDeployment(
    UUID deploymentId,
    UUID modelVersionId,
    DeploymentEnvironment environment,
    DeploymentStrategy strategy,
    String stationIdsJson,
    double trafficRatio,
    UUID requestedBy,
    UUID rollbackModelVersionId,
    UUID qualityApprovedBy,
    Instant qualityApprovedAt,
    UUID approvedBy,
    Instant approvedAt,
    String warmupEvidenceSha256,
    String metricsGateSha256,
    String rollbackEvidenceSha256,
    DeploymentStatus status,
    Instant createdAt,
    long recordVersion
) {

    public ModelDeployment {
        Objects.requireNonNull(deploymentId);
        Objects.requireNonNull(modelVersionId);
        Objects.requireNonNull(environment);
        Objects.requireNonNull(strategy);
        Objects.requireNonNull(status);
        Objects.requireNonNull(createdAt);
        if ((requestedBy == null) != (rollbackModelVersionId == null)) {
            throw new DomainViolation("部署请求人与回滚模型版本必须同时存在或同时缺失");
        }
        if (rollbackModelVersionId != null
                && rollbackModelVersionId.equals(modelVersionId)) {
            throw new DomainViolation("部署必须绑定不同于当前版本的回滚模型版本");
        }
        if (recordVersion < 0) {
            throw new DomainViolation("部署记录版本不能为负数");
        }
        if (strategy == DeploymentStrategy.PERCENTAGE
                && (trafficRatio < 0.0 || trafficRatio > 1.0)) {
            throw new DomainViolation("百分比策略的流量比例必须在 0.0 到 1.0 之间");
        }
        if (strategy == DeploymentStrategy.STATION
                && (stationIdsJson == null
                    || stationIdsJson.isBlank()
                    || stationIdsJson.equals("[]"))) {
            throw new DomainViolation("工位策略必须包含至少一个工位 ID");
        }
        if (environment == DeploymentEnvironment.SHADOW && trafficRatio != 0.0) {
            throw new DomainViolation("影子环境不得承载生产流量");
        }
        if ((qualityApprovedBy == null) != (qualityApprovedAt == null)) {
            throw new DomainViolation("质量审批人和时间必须成对存在");
        }
        if ((approvedBy == null) != (approvedAt == null)) {
            throw new DomainViolation("发布审批人和时间必须成对存在");
        }
        if (warmupEvidenceSha256 != null
                && !warmupEvidenceSha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("预热证据必须是 SHA-256");
        }
        if (metricsGateSha256 != null
                && !metricsGateSha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("灰度门槛证据必须是 SHA-256");
        }
        if (rollbackEvidenceSha256 != null
                && !rollbackEvidenceSha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("回滚运行证据必须是 SHA-256");
        }
        if (approvedBy != null
                && (qualityApprovedBy == null || approvedBy.equals(qualityApprovedBy))) {
            throw new DomainViolation("质量审批人与发布审批人必须独立");
        }
    }

    /**
     * V8 对历史部署不猜测请求人和模型级回滚目标；历史行只能查询，不能继续推进状态。
     */
    public boolean hasCompleteReleaseContext() {
        return requestedBy != null && rollbackModelVersionId != null;
    }

    private void requireCompleteReleaseContext() {
        if (!hasCompleteReleaseContext()) {
            throw new DomainViolation(
                "历史部署缺少发布上下文，当前只能 HOLD，禁止审批、激活或回滚"
            );
        }
    }

    public ModelDeployment withApproval(
            DeploymentApprovalRole role, UUID approverId, Instant at) {
        if (status != DeploymentStatus.REQUESTED) {
            throw new DomainViolation("只能审批处于请求状态的部署");
        }
        requireCompleteReleaseContext();
        Objects.requireNonNull(role);
        Objects.requireNonNull(approverId);
        Objects.requireNonNull(at);
        if (approverId.equals(requestedBy)) {
            throw new DomainViolation("部署请求人与审批人不能为同一人");
        }
        if (role == DeploymentApprovalRole.QUALITY_APPROVER) {
            if (qualityApprovedBy != null) {
                throw new DomainViolation("质量审批已存在");
            }
            DeploymentStatus next = approvedBy == null
                ? DeploymentStatus.REQUESTED : DeploymentStatus.APPROVED;
            return copy(
                approverId, at, approvedBy, approvedAt, next, recordVersion + 1);
        }
        if (approvedBy != null) {
            throw new DomainViolation("发布审批已存在");
        }
        DeploymentStatus next = qualityApprovedBy == null
            ? DeploymentStatus.REQUESTED : DeploymentStatus.APPROVED;
        return copy(
            qualityApprovedBy, qualityApprovedAt, approverId, at, next, recordVersion + 1);
    }

    public ModelDeployment withRejection() {
        if (status != DeploymentStatus.REQUESTED) {
            throw new DomainViolation("只能拒绝处于请求状态的部署");
        }
        requireCompleteReleaseContext();
        return copy(
            qualityApprovedBy, qualityApprovedAt, approvedBy, approvedAt,
            DeploymentStatus.REJECTED, recordVersion + 1);
    }

    public ModelDeployment withStatus(DeploymentStatus newStatus) {
        Objects.requireNonNull(newStatus);
        if (status == newStatus) {
            return this;
        }
        requireCompleteReleaseContext();
        if (status == DeploymentStatus.APPROVED && newStatus == DeploymentStatus.ACTIVE) {
            throw new DomainViolation("正式激活必须携带运行时验签、预热和门槛证据");
        }
        if (status == DeploymentStatus.ACTIVE && newStatus == DeploymentStatus.ROLLED_BACK) {
            throw new DomainViolation("正式回滚必须携带目标模型运行证据");
        }
        throw new DomainViolation(
            "不允许的状态转换: " + status.name() + " -> " + newStatus.name());
    }

    public ModelDeployment withActivation(
            String nextWarmupEvidenceSha256, String nextMetricsGateSha256) {
        if (status != DeploymentStatus.APPROVED) {
            throw new DomainViolation("只有完成双审批的部署可以激活");
        }
        requireCompleteReleaseContext();
        requireSha256(nextWarmupEvidenceSha256, "预热证据");
        requireSha256(nextMetricsGateSha256, "灰度门槛证据");
        return copy(
            qualityApprovedBy, qualityApprovedAt, approvedBy, approvedAt,
            nextWarmupEvidenceSha256, nextMetricsGateSha256, rollbackEvidenceSha256,
            DeploymentStatus.ACTIVE, recordVersion + 1);
    }

    public ModelDeployment withRollback(
            UUID targetModelVersionId, String nextRollbackEvidenceSha256) {
        if (status != DeploymentStatus.ACTIVE) {
            throw new DomainViolation("只能回滚处于激活状态的部署");
        }
        requireCompleteReleaseContext();
        if (targetModelVersionId == null
                || !targetModelVersionId.equals(rollbackModelVersionId)
                || targetModelVersionId.equals(modelVersionId)) {
            throw new DomainViolation("回滚目标必须等于登记的独立回滚模型版本");
        }
        requireSha256(nextRollbackEvidenceSha256, "回滚运行证据");
        return copy(
            qualityApprovedBy, qualityApprovedAt, approvedBy, approvedAt,
            warmupEvidenceSha256, metricsGateSha256, nextRollbackEvidenceSha256,
            DeploymentStatus.ROLLED_BACK, recordVersion + 1);
    }

    private ModelDeployment copy(
            UUID nextQualityApprovedBy,
            Instant nextQualityApprovedAt,
            UUID nextApprovedBy,
            Instant nextApprovedAt,
            DeploymentStatus nextStatus,
            long nextRecordVersion) {
        return copy(
            nextQualityApprovedBy, nextQualityApprovedAt,
            nextApprovedBy, nextApprovedAt,
            warmupEvidenceSha256, metricsGateSha256, rollbackEvidenceSha256,
            nextStatus, nextRecordVersion);
    }

    private ModelDeployment copy(
            UUID nextQualityApprovedBy,
            Instant nextQualityApprovedAt,
            UUID nextApprovedBy,
            Instant nextApprovedAt,
            String nextWarmupEvidenceSha256,
            String nextMetricsGateSha256,
            String nextRollbackEvidenceSha256,
            DeploymentStatus nextStatus,
            long nextRecordVersion) {
        return new ModelDeployment(
            deploymentId, modelVersionId, environment, strategy, stationIdsJson,
            trafficRatio, requestedBy, rollbackModelVersionId,
            nextQualityApprovedBy, nextQualityApprovedAt,
            nextApprovedBy, nextApprovedAt,
            nextWarmupEvidenceSha256, nextMetricsGateSha256, nextRollbackEvidenceSha256,
            nextStatus, createdAt,
            nextRecordVersion);
    }

    private static void requireSha256(String value, String field) {
        if (value == null || !value.matches("[0-9a-f]{64}")) {
            throw new DomainViolation(field + "必须是 SHA-256");
        }
    }
}
