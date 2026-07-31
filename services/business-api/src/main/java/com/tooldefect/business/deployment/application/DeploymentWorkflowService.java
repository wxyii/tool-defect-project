package com.tooldefect.business.deployment.application;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import com.tooldefect.business.deployment.domain.DeploymentApprovalRole;
import com.tooldefect.business.deployment.domain.DeploymentEnvironment;
import com.tooldefect.business.deployment.domain.DeploymentNotFound;
import com.tooldefect.business.deployment.domain.DeploymentStatus;
import com.tooldefect.business.deployment.domain.DeploymentStrategy;
import com.tooldefect.business.deployment.domain.ModelDeployment;
import com.tooldefect.business.model.application.ModelRepository;
import com.tooldefect.business.model.domain.ModelApprovalState;
import com.tooldefect.business.model.domain.ModelNotFound;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.Uuid7Generator;
import com.tooldefect.business.shared.domain.DomainViolation;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

@Service
public class DeploymentWorkflowService {

    private final DeploymentRepository deployments;
    private final ModelRepository models;
    private final IdempotencyService idempotency;
    private final Uuid7Generator identifiers;
    private final Clock clock;
    private final ObjectMapper json;

    public DeploymentWorkflowService(
            DeploymentRepository deployments,
            ModelRepository models,
            IdempotencyService idempotency,
            Uuid7Generator identifiers,
            Clock clock,
            ObjectMapper json) {
        this.deployments = Objects.requireNonNull(deployments);
        this.models = Objects.requireNonNull(models);
        this.idempotency = Objects.requireNonNull(idempotency);
        this.identifiers = Objects.requireNonNull(identifiers);
        this.clock = Objects.requireNonNull(clock);
        this.json = Objects.requireNonNull(json);
    }

    @Transactional
    public IdempotencyService.Response requestDeployment(
            String actorId, String idempotencyKey, Map<String, Object> request) {
        return idempotency.execute(
            "requestModelDeployment", actorId, idempotencyKey, request,
            () -> {
                UUID modelVersionId = requiredUuid(request, "model_version_id");
                UUID rollbackModelVersionId = requiredUuid(request, "rollback_model_version_id");
                if (modelVersionId.equals(rollbackModelVersionId)) {
                    throw new DomainViolation("回滚模型版本必须不同于当前部署版本");
                }
                requireApprovedModel(modelVersionId);
                requireApprovedModel(rollbackModelVersionId);

                DeploymentEnvironment environment = enumValue(
                    request, "environment", DeploymentEnvironment.class);
                DeploymentStrategy strategy = enumValue(
                    request, "strategy", DeploymentStrategy.class);
                List<UUID> stationIds = stationIds(request);
                double trafficRatio = requiredNumber(request, "traffic_ratio");
                if (environment == DeploymentEnvironment.SHADOW && trafficRatio != 0.0) {
                    throw new DomainViolation("影子环境的流量比例必须为 0");
                }
                UUID requestedBy = requiredActor(actorId);
                Instant createdAt = Instant.now(clock);

                var deployment = new ModelDeployment(
                    identifiers.next(),
                    modelVersionId,
                    environment,
                    strategy,
                    toJson(stationIds),
                    trafficRatio,
                    requestedBy,
                    rollbackModelVersionId,
                    null,
                    null,
                    null,
                    null,
                    null,
                    null,
                    null,
                    DeploymentStatus.REQUESTED,
                    createdAt,
                    0
                );

                deployments.insertDeployment(deployment);

                return new IdempotencyService.Response(202, Map.of(
                    "job_id", deployment.deploymentId().toString(),
                    "status", "QUEUED",
                    "poll_after_ms", 3000
                ));
            }
        );
    }

    @Transactional
    public IdempotencyService.Response approveDeployment(
            String actorId,
            String idempotencyKey,
            UUID deploymentId,
            long expectedRecordVersion,
            Map<String, Object> request) {
        return idempotency.execute(
            "approveModelDeployment:" + deploymentId, actorId, idempotencyKey, request,
            () -> {
                var deployment = deployments.findDeployment(deploymentId)
                    .orElseThrow(() -> new DeploymentNotFound(deploymentId));
                if (!deployment.hasCompleteReleaseContext()) {
                    throw new DomainViolation(
                        "历史部署缺少发布上下文，当前只能 HOLD，禁止审批"
                    );
                }
                requireRecordVersion(deployment, expectedRecordVersion);
                UUID approver = requiredActor(actorId);
                DeploymentApprovalRole role = enumValue(
                    request, "role", DeploymentApprovalRole.class);
                String decision = requiredText(request, "decision");
                String reason = requiredText(request, "reason");
                Instant now = Instant.now(clock);

                ModelDeployment updated;
                if ("APPROVE".equals(decision)) {
                    updated = deployment.withApproval(role, approver, now);
                } else if ("REJECT".equals(decision)) {
                    if (deployment.status() != DeploymentStatus.REQUESTED) {
                        throw new DomainViolation("只有请求状态的部署可以被拒绝");
                    }
                    if (approver.equals(deployment.requestedBy())) {
                        throw new DomainViolation("部署请求人与审批人不能为同一人");
                    }
                    updated = deployment.withRejection();
                } else {
                    throw new DomainViolation("审批决定必须是 APPROVE 或 REJECT");
                }

                deployments.appendApproval(
                    identifiers.next(), deploymentId, role, decision, approver, reason, now);
                deployments.updateDeployment(updated);

                return new IdempotencyService.Response(201, Map.of(
                    "accepted", true,
                    "request_id", deployment.deploymentId().toString()
                ));
            }
        );
    }

    @Transactional
    public IdempotencyService.Response rollbackDeployment(
            String actorId,
            String idempotencyKey,
            UUID deploymentId,
            long expectedRecordVersion,
            Map<String, Object> request) {
        return idempotency.execute(
            "rollbackModelDeployment:" + deploymentId, actorId, idempotencyKey, request,
            () -> {
                var deployment = deployments.findDeployment(deploymentId)
                    .orElseThrow(() -> new DeploymentNotFound(deploymentId));
                if (!deployment.hasCompleteReleaseContext()) {
                    throw new DomainViolation(
                        "历史部署缺少发布上下文，当前只能 HOLD，禁止回滚"
                    );
                }
                requireRecordVersion(deployment, expectedRecordVersion);
                UUID targetModelVersionId = requiredUuid(request, "target_model_version_id");
                requireApprovedModel(targetModelVersionId);
                String reason = requiredText(request, "reason");
                if (reason.isBlank()) {
                    throw new DomainViolation("回滚原因不能为空");
                }

                throw new DomainViolation(
                    "回滚请求不能直接改变部署状态，必须由已验证的运行编排器提交回滚证据"
                );
            }
        );
    }

    /** 仅供已接入推理运行槽的发布编排器调用；缺少真实运行证据时保持失败。 */
    @Transactional
    public Map<String, Object> activateDeployment(
            UUID deploymentId,
            long expectedRecordVersion,
            DeploymentRuntimeEvidence evidence) {
        var deployment = deployments.findDeployment(deploymentId)
            .orElseThrow(() -> new DeploymentNotFound(deploymentId));
        if (!deployment.hasCompleteReleaseContext()) {
            throw new DomainViolation("历史部署缺少发布上下文，当前只能 HOLD");
        }
        requireRecordVersion(deployment, expectedRecordVersion);
        requireApprovedModel(deployment.modelVersionId());
        Objects.requireNonNull(evidence);
        var active = deployment.withActivation(
            evidence.warmupEvidenceSha256(), evidence.metricsGateSha256());
        deployments.updateDeployment(active);
        return Map.of(
            "deployment_id", active.deploymentId().toString(),
            "status", active.status().name(),
            "record_version", active.recordVersion()
        );
    }

    /** 仅供已接入推理运行槽的发布编排器调用；缺少目标模型运行证据时保持失败。 */
    @Transactional
    public Map<String, Object> executeRollback(
            UUID deploymentId,
            long expectedRecordVersion,
            UUID targetModelVersionId,
            RollbackRuntimeEvidence evidence) {
        var deployment = deployments.findDeployment(deploymentId)
            .orElseThrow(() -> new DeploymentNotFound(deploymentId));
        if (!deployment.hasCompleteReleaseContext()) {
            throw new DomainViolation("历史部署缺少发布上下文，当前只能 HOLD");
        }
        requireRecordVersion(deployment, expectedRecordVersion);
        requireApprovedModel(deployment.modelVersionId());
        requireApprovedModel(targetModelVersionId);
        Objects.requireNonNull(evidence);
        var rolledBack = deployment.withRollback(
            targetModelVersionId, evidence.rollbackEvidenceSha256());
        deployments.updateDeployment(rolledBack);
        return Map.of(
            "deployment_id", rolledBack.deploymentId().toString(),
            "status", rolledBack.status().name(),
            "record_version", rolledBack.recordVersion()
        );
    }

    @Transactional(readOnly = true)
    public Map<String, Object> getDeployment(UUID deploymentId) {
        var deployment = deployments.findDeployment(deploymentId)
            .orElseThrow(() -> new DeploymentNotFound(deploymentId));
        return Map.of(
            "deployment_id", deployment.deploymentId().toString(),
            "model_version_id", deployment.modelVersionId().toString(),
            "environment", deployment.environment().name(),
            "strategy", deployment.strategy().name(),
            "status", deployment.status().name(),
            "record_version", deployment.recordVersion(),
            "created_at", deployment.createdAt().toString()
        );
    }

    private void requireApprovedModel(UUID modelVersionId) {
        var model = models.findVersion(modelVersionId)
            .orElseThrow(() -> new ModelNotFound(modelVersionId));
        if (model.approvalState() != ModelApprovalState.APPROVED
                || !model.hasCompleteSupplyChainEvidence()) {
            throw new DomainViolation("未批准的模型版本不得部署或作为回滚目标");
        }
    }

    private List<UUID> stationIds(Map<String, Object> request) {
        Object raw = request.get("station_ids");
        if (!(raw instanceof List<?> values)) {
            throw new DomainViolation("station_ids 必须是数组");
        }
        var result = new ArrayList<UUID>();
        var unique = new LinkedHashSet<UUID>();
        for (Object value : values) {
            if (!(value instanceof String text)) {
                throw new DomainViolation("station_ids 只能包含 UUID 文本");
            }
            UUID stationId;
            try {
                stationId = UUID.fromString(text);
            } catch (IllegalArgumentException error) {
                throw new DomainViolation("station_ids 包含非法 UUID");
            }
            if (!unique.add(stationId)) {
                throw new DomainViolation("station_ids 不能重复");
            }
            result.add(stationId);
        }
        return List.copyOf(result);
    }

    private String toJson(Object value) {
        try {
            return json.writeValueAsString(value);
        } catch (JacksonException error) {
            throw new DomainViolation("部署工位范围无法规范化");
        }
    }

    private static double requiredNumber(Map<String, Object> request, String field) {
        Object value = request.get(field);
        if (!(value instanceof Number number)
                || !Double.isFinite(number.doubleValue())
                || number.doubleValue() < 0.0
                || number.doubleValue() > 1.0) {
            throw new DomainViolation(field + " 必须是 0 到 1 之间的有限数字");
        }
        return number.doubleValue();
    }

    private static String requiredText(Map<String, Object> request, String field) {
        Object value = request.get(field);
        if (!(value instanceof String text) || text.isBlank() || text.length() > 2000) {
            throw new DomainViolation(field + " 不能为空且不能超过 2000 字符");
        }
        return text;
    }

    private static UUID requiredUuid(Map<String, Object> request, String field) {
        Object value = request.get(field);
        if (!(value instanceof String text)) {
            throw new DomainViolation(field + " 不能为空");
        }
        try {
            return UUID.fromString(text);
        } catch (IllegalArgumentException error) {
            throw new DomainViolation(field + " 不是合法 UUID");
        }
    }

    private static UUID requiredActor(String actorId) {
        try {
            return UUID.fromString(actorId);
        } catch (IllegalArgumentException error) {
            throw new DomainViolation("未认证用户不能创建、审批或回滚部署");
        }
    }

    private static <T extends Enum<T>> T enumValue(
            Map<String, Object> request, String field, Class<T> type) {
        Object value = request.get(field);
        if (!(value instanceof String text)) {
            throw new DomainViolation(field + " 不能为空");
        }
        try {
            return Enum.valueOf(type, text);
        } catch (IllegalArgumentException error) {
            throw new DomainViolation(field + " 枚举值不合法");
        }
    }

    private static void requireRecordVersion(ModelDeployment deployment, long expected) {
        if (expected < 0 || deployment.recordVersion() != expected) {
            throw new DomainViolation("部署版本已变化，请重新读取后重试");
        }
    }
}
