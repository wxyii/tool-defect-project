package com.tooldefect.business.deployment.api;

import com.tooldefect.business.deployment.application.DeploymentQueryRepository;
import com.tooldefect.business.deployment.application.DeploymentWorkflowService;
import com.tooldefect.business.identity.application.LocalIdentity;
import com.tooldefect.business.shared.api.ContractValues;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
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
public final class DeploymentController {

    private static final Set<String> CREATE_DEPLOYMENT_FIELDS = Set.of(
        "model_version_id", "environment", "strategy",
        "station_ids", "traffic_ratio", "rollback_model_version_id"
    );

    private static final Set<String> APPROVAL_FIELDS = Set.of(
        "role", "decision", "reason"
    );

    private static final Set<String> ROLLBACK_FIELDS = Set.of(
        "target_model_version_id", "reason"
    );

    private static final Set<String> DEPLOYMENT_STATES = Set.of(
        "REQUESTED", "APPROVED", "ACTIVE", "ROLLED_BACK", "REJECTED"
    );

    private final DeploymentWorkflowService deployments;
    private final DeploymentQueryRepository queries;

    public DeploymentController(DeploymentWorkflowService deployments, DeploymentQueryRepository queries) {
        this.deployments = Objects.requireNonNull(deployments);
        this.queries = Objects.requireNonNull(queries);
    }

    @GetMapping("/model-deployments")
    ResponseEntity<Map<String, Object>> listModelDeployments(
            @RequestParam(name = "model_version_id", required = false)
            UUID modelVersionId,
            @RequestParam(name = "status", required = false) String status,
            @RequestParam(name = "page_size", defaultValue = "50") int pageSize,
            @RequestParam(name = "cursor", required = false) String cursor,
            Authentication authentication) {
        if (pageSize < 1 || pageSize > 200) {
            throw new ContractValues.ContractInputViolation(
                "page_size 必须位于 1 到 200"
            );
        }
        if (status != null && !DEPLOYMENT_STATES.contains(status)) {
            throw new ContractValues.ContractInputViolation(
                "status 不是合法的部署状态"
            );
        }
        return ResponseEntity.ok(queries.listDeployments(
            actor(authentication), modelVersionId, status, pageSize, cursor
        ));
    }

    @PostMapping("/model-deployments")
    ResponseEntity<Map<String, Object>> createModelDeployment(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        var request = ContractValues.object(body, CREATE_DEPLOYMENT_FIELDS, "模型部署创建请求");
        ContractValues.uuid(request, "model_version_id");
        ContractValues.oneOf(request, "environment",
            Set.of("SHADOW", "CANARY", "PRODUCTION"));
        ContractValues.oneOf(request, "strategy",
            Set.of("STATION", "PERCENTAGE"));
        validateStationIds(request);
        ContractValues.number(request, "traffic_ratio", 0.0, 1.0);
        ContractValues.uuid(request, "rollback_model_version_id");
        var response = deployments.requestDeployment(actor(authentication), idempotencyKey, request);
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/model-deployments/{model_deployment_id}/approvals")
    ResponseEntity<Map<String, Object>> approveModelDeployment(
            @PathVariable("model_deployment_id") UUID deploymentId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader("If-Match") String ifMatch,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        var request = ContractValues.object(body, APPROVAL_FIELDS, "模型部署审批请求");
        ContractValues.oneOf(request, "role",
            Set.of("QUALITY_APPROVER", "MODEL_RELEASE_APPROVER"));
        ContractValues.oneOf(request, "decision", Set.of("APPROVE", "REJECT"));
        ContractValues.text(request, "reason", 1, 2000);
        requireApprovalPermission(authentication, (String) request.get("role"));
        var response = deployments.approveDeployment(
            actor(authentication), idempotencyKey, deploymentId,
            parseIfMatch(ifMatch), request);
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/model-deployments/{model_deployment_id}/rollback")
    ResponseEntity<Map<String, Object>> rollbackModelDeployment(
            @PathVariable("model_deployment_id") UUID deploymentId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader("If-Match") String ifMatch,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        var request = ContractValues.object(body, ROLLBACK_FIELDS, "模型部署回滚请求");
        ContractValues.uuid(request, "target_model_version_id");
        ContractValues.text(request, "reason", 1, 2000);
        var response = deployments.rollbackDeployment(
            actor(authentication), idempotencyKey, deploymentId,
            parseIfMatch(ifMatch), request);
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @GetMapping("/model-deployments/{model_deployment_id}")
    ResponseEntity<Map<String, Object>> getModelDeployment(
            @PathVariable("model_deployment_id") UUID deploymentId) {
        return ResponseEntity.ok(deployments.getDeployment(deploymentId));
    }

    private static void validateStationIds(Map<String, Object> request) {
        Object raw = request.get("station_ids");
        if (!(raw instanceof java.util.List<?> values) || values.size() > 1000) {
            throw new ContractValues.ContractInputViolation("station_ids 数组不合法");
        }
        var seen = new java.util.HashSet<UUID>();
        for (Object value : values) {
            if (!(value instanceof String text)) {
                throw new ContractValues.ContractInputViolation("station_ids 必须是 UUID 数组");
            }
            try {
                if (!seen.add(UUID.fromString(text))) {
                    throw new ContractValues.ContractInputViolation("station_ids 不能重复");
                }
            } catch (IllegalArgumentException invalid) {
                throw new ContractValues.ContractInputViolation("station_ids 包含非法 UUID", invalid);
            }
        }
    }

    private static long parseIfMatch(String value) {
        if (value == null) {
            throw new ContractValues.ContractInputViolation("If-Match 不能为空");
        }
        String normalized = value;
        if (normalized.startsWith("\"") && normalized.endsWith("\"")) {
            normalized = normalized.substring(1, normalized.length() - 1);
        }
        try {
            long version = Long.parseLong(normalized);
            if (version < 0) {
                throw new NumberFormatException("negative");
            }
            return version;
        } catch (NumberFormatException invalid) {
            throw new ContractValues.ContractInputViolation("If-Match 必须是非负记录版本", invalid);
        }
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

    private static void requireApprovalPermission(
            Authentication authentication, String role) {
        String required = "QUALITY_APPROVER".equals(role)
            ? "model:approve"
            : "model:deploy:approve";
        if (authentication == null
                || !authentication.getAuthorities().stream()
                    .anyMatch(authority -> required.equals(authority.getAuthority()))) {
            throw new AccessDeniedException("当前身份不能执行该职责的部署审批");
        }
    }
}
