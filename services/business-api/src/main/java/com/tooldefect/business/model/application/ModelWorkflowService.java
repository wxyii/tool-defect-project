package com.tooldefect.business.model.application;

import com.tooldefect.business.model.domain.ModelApprovalState;
import com.tooldefect.business.model.domain.ModelNotFound;
import com.tooldefect.business.model.domain.ModelVersion;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.LifecycleEligibilityReader;
import com.tooldefect.business.shared.application.Uuid7Generator;
import com.tooldefect.business.shared.domain.DomainViolation;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
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
    private final LifecycleEligibilityReader lifecycle;
    private final IdempotencyService idempotency;
    private final Uuid7Generator identifiers;
    private final Clock clock;
    private final ObjectMapper json;

    public ModelWorkflowService(
            ModelRepository models,
            LifecycleEligibilityReader lifecycle,
            IdempotencyService idempotency,
            Uuid7Generator identifiers,
            Clock clock,
            ObjectMapper json) {
        this.models = Objects.requireNonNull(models);
        this.lifecycle = Objects.requireNonNull(lifecycle);
        this.idempotency = Objects.requireNonNull(idempotency);
        this.identifiers = Objects.requireNonNull(identifiers);
        this.clock = Objects.requireNonNull(clock);
        this.json = Objects.requireNonNull(json);
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
    public IdempotencyService.Response registerVersion(
            String actorId, String idempotencyKey, Map<String, Object> request) {
        return idempotency.execute(
            "registerModelVersion", actorId, idempotencyKey, request,
            () -> {
                var modelId = requiredUuid(request, "model_id");
                var trainingRunId = requiredUuid(request, "training_run_id");
                var datasetVersionId = requiredUuid(request, "dataset_version_id");
                requireCompletedTraining(trainingRunId, datasetVersionId);
                requireFrozenDataset(datasetVersionId);
                var registryName = (String) request.get("registry_name");
                var registryVersion = (String) request.get("registry_version");
                var artifactBucket = (String) request.get("artifact_bucket");
                var artifactObjectKey = (String) request.get("artifact_object_key");
                var artifactSha256 = (String) request.get("artifact_sha256");
                var sbomSha256 = (String) request.get("sbom_sha256");
                var signatureKeyId = (String) request.get("signature_key_id");
                var inputSpecJson = toJson(objectValue(request, "input_spec"));
                var outputSpecJson = toJson(objectValue(request, "output_spec"));
                var evaluation = objectValue(request, "evaluation_summary");
                var evaluationSummaryJson = toJson(evaluation);
                var evaluationReportSha256 = requiredSha256(evaluation, "evaluation_report_sha256");
                var thresholdGateSha256 = requiredSha256(evaluation, "threshold_gate_sha256");
                var registeredBy = requiredActor(actorId);

                var latest = models.findLatestVersion(modelId);
                int nextVersion = latest.map(v -> v.version() + 1).orElse(1);

                var version = new ModelVersion(
                    identifiers.next(),
                    modelId,
                    nextVersion,
                    trainingRunId,
                    datasetVersionId,
                    registryName, registryVersion, artifactBucket, artifactObjectKey,
                    artifactSha256, sbomSha256, signatureKeyId,
                    inputSpecJson,
                    outputSpecJson,
                    evaluationSummaryJson,
                    evaluationReportSha256,
                    thresholdGateSha256,
                    ModelApprovalState.CANDIDATE,
                    registeredBy,
                    null,
                    null,
                    null,
                    null,
                    Instant.now(clock)
                );

                models.insertVersion(version);

                return new IdempotencyService.Response(201, Map.of(
                    "model_version_id", version.modelVersionId().toString(),
                    "version", version.version(),
                    "approval_state", version.approvalState().name(),
                    "created_at", version.createdAt().toString()
                ));
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

    private static UUID requiredUuid(Map<String, Object> request, String field) {
        Object value = request.get(field);
        if (!(value instanceof String text) || text.isBlank()) {
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
            throw new DomainViolation("未认证用户不能登记或审批模型");
        }
    }

    private void requireCompletedTraining(UUID trainingRunId, UUID datasetVersionId) {
        var training = lifecycle.findTraining(trainingRunId)
            .orElseThrow(() -> new DomainViolation("模型来源训练运行不存在"));
        if (!training.datasetVersionId().equals(datasetVersionId)
                || !training.hasSuccessfulEvidence()) {
            throw new DomainViolation(
                "模型只能来自绑定同一冻结数据集且具有完成证据的成功训练运行"
            );
        }
    }

    private void requireFrozenDataset(UUID datasetVersionId) {
        var dataset = lifecycle.findDataset(datasetVersionId)
            .orElseThrow(() -> new DomainViolation("模型来源数据集版本不存在"));
        if (!dataset.isFrozenWithManifest()) {
            throw new DomainViolation("模型只能引用具有不可变清单的冻结数据集版本");
        }
    }

    private static Map<String, Object> objectValue(Map<String, Object> request, String field) {
        Object value = request.get(field);
        if (!(value instanceof Map<?, ?> raw)) {
            throw new DomainViolation(field + " 必须是 JSON 对象");
        }
        Map<String, Object> result = new java.util.LinkedHashMap<>();
        for (var entry : raw.entrySet()) {
            if (!(entry.getKey() instanceof String key)) {
                throw new DomainViolation(field + " 包含非字符串键");
            }
            result.put(key, entry.getValue());
        }
        return result;
    }

    private String toJson(Object value) {
        try {
            return json.writeValueAsString(value);
        } catch (JacksonException error) {
            throw new DomainViolation("模型证据 JSON 无法规范化");
        }
    }

    private static String requiredSha256(Map<String, Object> value, String field) {
        Object raw = value.get(field);
        if (!(raw instanceof String text) || !text.matches("[0-9a-f]{64}")) {
            throw new DomainViolation(field + " 必须是合法 SHA-256 十六进制");
        }
        return text;
    }

    private static String requiredReason(Map<String, Object> request) {
        Object raw = request.get("reason");
        if (!(raw instanceof String text) || text.isBlank() || text.length() > 2000) {
            throw new DomainViolation("验证决定原因不能为空且不能超过 2000 字符");
        }
        return text;
    }
}
