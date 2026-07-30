package com.tooldefect.business.detection.api;

import java.util.Map;
import java.util.Set;
import java.util.UUID;

import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.tooldefect.business.detection.application.DetectionQueryService;
import com.tooldefect.business.shared.api.ContractValues;

@RestController
@RequestMapping("/api/v1/detections")
public final class DetectionQueryController {
    private static final Set<String> DISPOSITIONS =
        Set.of("PASS", "FAIL", "HOLD");
    private static final Set<String> OUTCOMES =
        Set.of("QUALIFIED", "UNQUALIFIED", "INCONCLUSIVE");

    private final DetectionQueryService detections;

    public DetectionQueryController(DetectionQueryService detections) {
        this.detections = java.util.Objects.requireNonNull(detections);
    }

    @GetMapping
    ResponseEntity<Map<String, Object>> listDetections(
            @RequestParam(name = "cursor", required = false) String cursor,
            @RequestParam(name = "page_size", defaultValue = "25") int pageSize,
            @RequestParam(
                name = "business_disposition",
                required = false
            ) String businessDisposition,
            @RequestParam(
                name = "algorithm_outcome",
                required = false
            ) String algorithmOutcome,
            @RequestParam(
                name = "model_version",
                required = false
            ) String modelVersion,
            Authentication authentication) {
        if (pageSize < 1 || pageSize > 100) {
            throw new ContractValues.ContractInputViolation(
                "page_size 必须位于 1 到 100"
            );
        }
        requireOptionalEnum(
            businessDisposition,
            DISPOSITIONS,
            "business_disposition"
        );
        requireOptionalEnum(
            algorithmOutcome,
            OUTCOMES,
            "algorithm_outcome"
        );
        if (modelVersion != null
                && (modelVersion.isBlank() || modelVersion.length() > 128)) {
            throw new ContractValues.ContractInputViolation(
                "model_version 不合法"
            );
        }
        return ResponseEntity.ok(detections.list(
            actor(authentication),
            cursor,
            pageSize,
            businessDisposition,
            algorithmOutcome,
            modelVersion
        ));
    }

    @GetMapping("/{detection_task_id}")
    ResponseEntity<Map<String, Object>> getDetection(
            @PathVariable("detection_task_id") UUID detectionTaskId,
            Authentication authentication) {
        return ResponseEntity.ok(detections.detail(
            actor(authentication),
            detectionTaskId
        ));
    }

    private static String actor(Authentication authentication) {
        if (authentication == null
                || authentication.getName() == null
                || authentication.getName().isBlank()) {
            throw new DetectionIdentityViolation("用户身份缺失");
        }
        return authentication.getName();
    }

    private static void requireOptionalEnum(
            String value,
            Set<String> allowed,
            String field) {
        if (value != null && !allowed.contains(value)) {
            throw new ContractValues.ContractInputViolation(
                field + " 不属于冻结枚举"
            );
        }
    }

    public static final class DetectionIdentityViolation
            extends RuntimeException {
        DetectionIdentityViolation(String message) {
            super(message);
        }
    }
}
