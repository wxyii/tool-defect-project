package com.tooldefect.business.dataset.api;

import com.tooldefect.business.dataset.application.DatasetQueryService;
import com.tooldefect.business.dataset.application.DatasetWorkflowService;
import com.tooldefect.business.identity.application.LocalIdentity;
import com.tooldefect.business.shared.api.ContractValues;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

@RestController
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
@RequestMapping("/api/v1")
public final class DatasetController {

    private static final Set<String> CREATE_DATASET_FIELDS = Set.of(
        "dataset_name", "purpose"
    );

    private static final Set<String> CREATE_FIELDS = Set.of(
        "dataset_id", "candidate_manifest_id", "purpose"
    );

    private static final Set<String> VERSION_STATES = Set.of(
        "BUILDING", "VALIDATING", "FROZEN", "REJECTED"
    );

    private final DatasetWorkflowService datasets;
    private final DatasetQueryService queries;

    public DatasetController(DatasetWorkflowService datasets, DatasetQueryService queries) {
        this.datasets = Objects.requireNonNull(datasets);
        this.queries = Objects.requireNonNull(queries);
    }

    @GetMapping("/datasets")
    ResponseEntity<Map<String, Object>> listDatasets(
            @RequestParam(name = "page_size", defaultValue = "50") int pageSize,
            @RequestParam(name = "cursor", required = false) String cursor,
            Authentication authentication) {
        requirePageSize(pageSize, 200);
        return ResponseEntity.ok(
            queries.listDatasets(actor(authentication), pageSize, cursor)
        );
    }

    @PostMapping("/datasets")
    ResponseEntity<Map<String, Object>> createDataset(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        var request = ContractValues.object(
            body, CREATE_DATASET_FIELDS, "数据集创建请求"
        );
        ContractValues.text(request, "dataset_name", 1, 128);
        ContractValues.text(request, "purpose", 1, 128);
        var response = datasets.createDataset(
            actor(authentication), idempotencyKey, request
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @GetMapping("/dataset-versions")
    ResponseEntity<Map<String, Object>> listDatasetVersionCatalog(
            @RequestParam(name = "dataset_id", required = false) UUID datasetId,
            @RequestParam(name = "status", required = false) String status,
            @RequestParam(name = "page_size", defaultValue = "50") int pageSize,
            @RequestParam(name = "cursor", required = false) String cursor,
            Authentication authentication) {
        requirePageSize(pageSize, 200);
        if (status != null && !VERSION_STATES.contains(status)) {
            throw new ContractValues.ContractInputViolation(
                "status 不是合法的数据集版本状态"
            );
        }
        return ResponseEntity.ok(queries.listVersions(
            actor(authentication), datasetId, status, pageSize, cursor
        ));
    }

    @PostMapping("/dataset-versions")
    ResponseEntity<Map<String, Object>> createDatasetVersion(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> body,
        Authentication authentication) {
        var request = ContractValues.object(body, CREATE_FIELDS, "数据集版本创建请求");
        ContractValues.uuid(request, "dataset_id");
        ContractValues.uuid(request, "candidate_manifest_id");
        ContractValues.text(request, "purpose", 1, 256);
        var response = datasets.createVersion(actor(authentication), idempotencyKey, request);
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @GetMapping("/dataset-versions/{dataset_version_id}")
    ResponseEntity<Map<String, Object>> getDatasetVersion(
            @PathVariable("dataset_version_id") UUID datasetVersionId) {
        return ResponseEntity.ok(datasets.getVersion(datasetVersionId));
    }

    @GetMapping("/datasets/{dataset_id}/versions")
    ResponseEntity<Map<String, Object>> listDatasetVersions(
            @PathVariable("dataset_id") UUID datasetId,
            @RequestParam(name = "page_size", defaultValue = "25") int pageSize,
            @RequestParam(name = "cursor", required = false) String cursor,
            Authentication authentication) {
        if (pageSize < 1 || pageSize > 200) {
            throw new ContractValues.ContractInputViolation("page_size 必须位于 1 到 200");
        }
        return ResponseEntity.ok(queries.listVersions(actor(authentication), datasetId, pageSize, cursor));
    }

    @GetMapping("/dataset-versions/{dataset_version_id}/detail")
    ResponseEntity<Map<String, Object>> detailDatasetVersion(
            @PathVariable("dataset_version_id") UUID datasetVersionId,
            Authentication authentication) {
        return ResponseEntity.ok(queries.detailVersion(actor(authentication), datasetVersionId));
    }

    @GetMapping("/dataset-candidates")
    ResponseEntity<Map<String, Object>> listCandidates(
            @RequestParam(name = "status", required = false) String status,
            @RequestParam(name = "page_size", defaultValue = "25") int pageSize,
            @RequestParam(name = "cursor", required = false) String cursor,
            Authentication authentication) {
        if (pageSize < 1 || pageSize > 100) {
            throw new ContractValues.ContractInputViolation("page_size 必须位于 1 到 100");
        }
        return ResponseEntity.ok(queries.listCandidates(actor(authentication), status, pageSize, cursor));
    }

    @GetMapping("/dataset-versions/diff")
    ResponseEntity<Map<String, Object>> diffVersions(
            @RequestParam("from") UUID fromVersionId,
            @RequestParam("to") UUID toVersionId) {
        return ResponseEntity.ok(queries.diffVersions(fromVersionId, toVersionId));
    }

    @PostMapping("/dataset-versions/{dataset_version_id}/approval")
    ResponseEntity<Map<String, Object>> approveVersion(
            @PathVariable("dataset_version_id") UUID datasetVersionId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        var response = datasets.approveVersion(
            actor(authentication), idempotencyKey, datasetVersionId, body);
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

    private static void requirePageSize(int pageSize, int maximum) {
        if (pageSize < 1 || pageSize > maximum) {
            throw new ContractValues.ContractInputViolation(
                "page_size 必须位于 1 到 " + maximum
            );
        }
    }
}
