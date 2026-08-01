package com.tooldefect.business.model.api;

import com.tooldefect.business.model.application.ModelQueryRepository;
import com.tooldefect.business.model.application.ModelWorkflowService;
import com.tooldefect.business.identity.application.LocalIdentity;
import com.tooldefect.business.shared.api.ContractValues;

import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

@RestController
@RequestMapping("/api/v1")
public final class ModelController {

    private static final Set<String> CREATE_MODEL_FIELDS = Set.of(
        "model_name", "task_type"
    );

    private static final Set<String> REGISTER_FIELDS = Set.of(
        "model_id", "training_run_id", "dataset_version_id",
        "registry_name", "registry_version", "artifact_sha256",
        "artifact_bucket", "artifact_object_key", "sbom_sha256",
        "signature_key_id", "input_spec", "output_spec", "evaluation_summary"
    );

    private static final Set<String> VALIDATION_DECISION_FIELDS = Set.of(
        "decision", "reason", "evaluation_report_sha256"
    );

    private static final Set<String> APPROVAL_STATES = Set.of(
        "CANDIDATE", "VALIDATED", "APPROVED", "REJECTED", "RETIRED"
    );

    private final ModelWorkflowService models;
    private final ModelQueryRepository queries;

    public ModelController(ModelWorkflowService models, ModelQueryRepository queries) {
        this.models = Objects.requireNonNull(models);
        this.queries = Objects.requireNonNull(queries);
    }

    @GetMapping("/models")
    ResponseEntity<Map<String, Object>> listModels(
            @RequestParam(name = "page_size", defaultValue = "50") int pageSize,
            @RequestParam(name = "cursor", required = false) String cursor,
            Authentication authentication) {
        if (pageSize < 1 || pageSize > 200) {
            throw new ContractValues.ContractInputViolation(
                "page_size 必须位于 1 到 200"
            );
        }
        return ResponseEntity.ok(
            queries.listModels(actor(authentication), pageSize, cursor)
        );
    }

    @PostMapping("/models")
    ResponseEntity<Map<String, Object>> createModel(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        var request = ContractValues.object(
            body, CREATE_MODEL_FIELDS, "模型创建请求"
        );
        ContractValues.text(request, "model_name", 1, 128);
        ContractValues.text(request, "task_type", 1, 64);
        var response = models.createModel(
            actor(authentication), idempotencyKey, request
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/model-versions")
    ResponseEntity<Map<String, Object>> registerModelVersion(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        var request = ContractValues.object(body, REGISTER_FIELDS, "模型版本注册请求");
        ContractValues.uuid(request, "model_id");
        ContractValues.uuid(request, "training_run_id");
        ContractValues.uuid(request, "dataset_version_id");
        ContractValues.text(request, "registry_name", 1, 256);
        ContractValues.text(request, "registry_version", 1, 128);
        ContractValues.text(request, "artifact_bucket", 1, 128);
        ContractValues.text(request, "artifact_object_key", 1, 1024);
        ContractValues.sha256(request, "artifact_sha256");
        ContractValues.sha256(request, "sbom_sha256");
        ContractValues.text(request, "signature_key_id", 1, 256);
        requireObject(request, "input_spec");
        requireObject(request, "output_spec");
        var evaluation = requireObject(request, "evaluation_summary");
        ContractValues.sha256(evaluation, "evaluation_report_sha256");
        ContractValues.sha256(evaluation, "threshold_gate_sha256");
        var response = models.registerVersion(actor(authentication), idempotencyKey, request);
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @GetMapping("/model-versions")
    ResponseEntity<Map<String, Object>> listModelVersions(
            @RequestParam(name = "model_id", required = false) UUID modelId,
            @RequestParam(name = "approval_state", required = false)
            String approvalState,
            @RequestParam(name = "page_size", defaultValue = "25") int pageSize,
            @RequestParam(name = "cursor", required = false) String cursor,
            Authentication authentication) {
        if (pageSize < 1 || pageSize > 100) {
            throw new ContractValues.ContractInputViolation("page_size 必须位于 1 到 100");
        }
        if (approvalState != null && !APPROVAL_STATES.contains(approvalState)) {
            throw new ContractValues.ContractInputViolation(
                "approval_state 不是合法的模型审批状态"
            );
        }
        return ResponseEntity.ok(queries.listVersions(
            actor(authentication), modelId, approvalState, pageSize, cursor
        ));
    }

    @GetMapping("/model-versions/{model_version_id}")
    ResponseEntity<Map<String, Object>> getModelVersion(
            @PathVariable("model_version_id") UUID modelVersionId) {
        return ResponseEntity.ok(models.getVersion(modelVersionId));
    }

    @PostMapping("/model-versions/{model_version_id}/validation-decisions")
    ResponseEntity<Map<String, Object>> submitModelValidationDecision(
            @PathVariable("model_version_id") UUID modelVersionId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        var request = ContractValues.object(body, VALIDATION_DECISION_FIELDS, "模型验证决定请求");
        ContractValues.oneOf(request, "decision", Set.of("APPROVE", "REJECT"));
        ContractValues.text(request, "reason", 1, 2000);
        ContractValues.sha256(request, "evaluation_report_sha256");
        var response = models.submitValidation(actor(authentication), idempotencyKey, modelVersionId, request);
        return ResponseEntity.status(response.status()).body(response.body());
    }

    private static String actor(Authentication authentication) {
        if (authentication == null || !authentication.isAuthenticated()) {
            return "anonymous";
        }
        if (authentication.getPrincipal() instanceof LocalIdentity identity) {
            return identity.userId().toString();
        }
        if (authentication.getPrincipal() instanceof Jwt jwt) {
            return jwt.getSubject();
        }
        return authentication.getName();
    }

    private static Map<String, Object> requireObject(Map<String, Object> request, String field) {
        Object raw = request.get(field);
        if (!(raw instanceof Map<?, ?> value)) {
            throw new ContractValues.ContractInputViolation(field + " 必须是对象");
        }
        Map<String, Object> result = new java.util.LinkedHashMap<>();
        for (var entry : value.entrySet()) {
            if (!(entry.getKey() instanceof String key)) {
                throw new ContractValues.ContractInputViolation(field + " 包含非字符串键");
            }
            result.put(key, entry.getValue());
        }
        return result;
    }
}
