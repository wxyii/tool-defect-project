package com.tooldefect.business.model.application;

import com.tooldefect.business.model.domain.ModelApprovalState;
import com.tooldefect.business.model.domain.ModelNotFound;
import com.tooldefect.business.model.domain.ModelVersion;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.Uuid7Generator;
import com.tooldefect.business.shared.domain.DomainViolation;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

@Service
public class ModelWorkflowService {

    private final ModelRepository models;
    private final IdempotencyService idempotency;
    private final Uuid7Generator identifiers;
    private final Clock clock;

    public ModelWorkflowService(
            ModelRepository models,
            IdempotencyService idempotency,
            Uuid7Generator identifiers,
            Clock clock) {
        this.models = Objects.requireNonNull(models);
        this.idempotency = Objects.requireNonNull(idempotency);
        this.identifiers = Objects.requireNonNull(identifiers);
        this.clock = Objects.requireNonNull(clock);
    }

    @Transactional
    public IdempotencyService.Response createModel(
            String actorId,
            String idempotencyKey,
            Map<String, Object> request) {
        return idempotency.execute(
            "createModel",
            actorId,
            idempotencyKey,
            request,
            () -> {
                UUID modelId = identifiers.next();
                String modelName = String.valueOf(request.get("model_name"));
                String taskType = String.valueOf(request.get("task_type"));
                Instant createdAt = Instant.now(clock);
                models.insertModel(modelId, modelName, taskType, createdAt);
                Map<String, Object> body = new LinkedHashMap<>();
                body.put("model_id", modelId.toString());
                body.put("model_name", modelName);
                body.put("task_type", taskType);
                body.put("version_count", 0);
                body.put("latest_version", null);
                body.put("latest_approval_state", null);
                body.put("created_at", createdAt.toString());
                return new IdempotencyService.Response(201, body);
            }
        );
    }

    @Transactional
    public IdempotencyService.Response submitValidation(
            String actorId, String idempotencyKey, UUID modelVersionId, Map<String, Object> request) {
        return idempotency.execute(
            "submitModelValidationDecision:" + modelVersionId, actorId, idempotencyKey, request,
            () -> {
                var version = models.findVersion(modelVersionId)
                    .orElseThrow(() -> new ModelNotFound(modelVersionId));

                if (version.approvalState() == ModelApprovalState.APPROVED) {
                    return acknowledgement(version.modelVersionId());
                }

                if (version.approvalState() == ModelApprovalState.REJECTED) {
                    return acknowledgement(version.modelVersionId());
                }

                var decision = (String) request.get("decision");
                var evaluationReportSha256 = (String) request.get("evaluation_report_sha256");
                if (!Objects.equals(evaluationReportSha256, version.evaluationReportSha256())) {
                    throw new DomainViolation("验证请求的评估报告哈希与登记版本不一致");
                }
                var approver = requiredActor(actorId);

                ModelVersion updated;
                if ("APPROVE".equals(decision)) {
                    updated = version.approvalState() == ModelApprovalState.CANDIDATE
                        ? version.withValidation(approver, Instant.now(clock))
                        : version.withFinalApproval(approver, Instant.now(clock));
                } else if ("REJECT".equals(decision)) {
                    updated = version.withRejection();
                } else {
                    throw new DomainViolation("验证决定必须是 APPROVE 或 REJECT");
                }

                var reason = requiredReason(request);
                models.updateVersion(updated);
                models.appendApproval(
                    identifiers.next(),
                    updated.modelVersionId(),
                    version.approvalState() == ModelApprovalState.CANDIDATE
                        ? "VALIDATION" : "RELEASE",
                    decision,
                    approver,
                    reason,
                    Instant.now(clock)
                );

                return acknowledgement(updated.modelVersionId());
            }
        );
    }

    private static IdempotencyService.Response acknowledgement(UUID requestId) {
        return new IdempotencyService.Response(201, Map.of(
            "accepted", true,
            "request_id", requestId.toString()
        ));
    }

    @Transactional(readOnly = true)
    public Map<String, Object> getVersion(UUID modelVersionId) {
        var version = models.findVersion(modelVersionId)
            .orElseThrow(() -> new ModelNotFound(modelVersionId));
        if (!version.hasCompleteSupplyChainEvidence()) {
            throw new DomainViolation(
                "历史模型版本缺少供应链证据，当前只能 HOLD，不能按生产模型返回"
            );
        }
        return Map.of(
            "model_version_id", version.modelVersionId().toString(),
            "model_id", version.modelId().toString(),
            "version", version.version(),
            "registry_name", version.registryName(),
            "registry_version", version.registryVersion(),
            "artifact_sha256", version.artifactSha256(),
            "approval_state", version.approvalState().name(),
            "created_at", version.createdAt().toString()
        );
    }

    private static UUID requiredActor(String actorId) {
        try {
            return UUID.fromString(actorId);
        } catch (IllegalArgumentException error) {
            throw new DomainViolation("未认证用户不能登记或审批模型");
        }
    }

    private static String requiredReason(Map<String, Object> request) {
        Object raw = request.get("reason");
        if (!(raw instanceof String text) || text.isBlank() || text.length() > 2000) {
            throw new DomainViolation("验证决定原因不能为空且不能超过 2000 字符");
        }
        return text;
    }
}
