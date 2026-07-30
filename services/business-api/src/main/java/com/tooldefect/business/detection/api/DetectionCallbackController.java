package com.tooldefect.business.detection.api;

import static com.tooldefect.business.shared.api.ContractValues.*;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.OptionalDouble;
import java.util.Set;
import java.util.UUID;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.tooldefect.business.detection.application.DetectionFailureSubmission;
import com.tooldefect.business.detection.application.DetectionResultSubmission;
import com.tooldefect.business.detection.application.DetectionWorkflowService;
import com.tooldefect.business.shared.api.ContractValues;

@RestController
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
@RequestMapping("/internal/v1")
public final class DetectionCallbackController {
    private static final Set<String> START_FIELDS = Set.of(
        "message_id", "worker_id", "runtime_version", "model_sha256"
    );
    private static final Set<String> RESULT_FIELDS = Set.of(
        "schema_version", "capture_id", "detection_task_id", "attempt_id",
        "execution_status", "algorithm_outcome", "confidence",
        "class_probabilities", "preprocess", "algorithm", "regions",
        "artifacts", "timings_ms", "warnings"
    );
    private static final Set<String> PROBABILITY_FIELDS = Set.of(
        "qualified", "unqualified"
    );
    private static final Set<String> PREPROCESS_FIELDS = Set.of(
        "plugin_id", "plugin_version", "config_sha256", "quality_status",
        "warnings"
    );
    private static final Set<String> ALGORITHM_FIELDS = Set.of(
        "plugin_id", "plugin_version", "model_version", "model_sha256"
    );
    private static final Set<String> TIMING_FIELDS = Set.of(
        "download", "decode", "preprocess", "inference", "postprocess", "upload"
    );
    private static final Set<String> REGION_FIELDS = Set.of(
        "region_id", "coordinate_space", "geometry_type", "geometry",
        "scores", "attributes"
    );
    private static final Set<String> ARTIFACT_FIELDS = Set.of(
        "kind", "image_id", "object"
    );
    private static final Set<String> OBJECT_REQUIRED_FIELDS = Set.of(
        "bucket", "object_key", "sha256", "size_bytes", "media_type"
    );
    private static final Set<String> FAILURE_FIELDS = Set.of(
        "error_code", "stage", "retryable", "message", "occurred_at"
    );

    private final DetectionWorkflowService detections;

    public DetectionCallbackController(DetectionWorkflowService detections) {
        this.detections = java.util.Objects.requireNonNull(detections);
    }

    @PostMapping("/detection-tasks/{detection_task_id}/attempts")
    ResponseEntity<Map<String, Object>> startDetectionAttempt(
            @PathVariable("detection_task_id") UUID detectionTaskId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader("traceparent") String traceparent,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        Map<String, Object> request = object(
            body,
            START_FIELDS,
            "执行尝试开始请求"
        );
        String messageId = uuid(request, "message_id").toString();
        var response = detections.startAttempt(
            detectionTaskId,
            messageId,
            text(request, "worker_id", 1, 128),
            text(request, "runtime_version", 1, 128),
            sha256(request, "model_sha256"),
            traceId(traceparent),
            actorId(authentication),
            idempotencyKey,
            request
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PutMapping("/detection-attempts/{attempt_id}/result")
    ResponseEntity<Map<String, Object>> submitDetectionResult(
            @PathVariable("attempt_id") UUID attemptId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader("traceparent") String traceparent,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        traceId(traceparent);
        DetectionResultSubmission result = result(body);
        var response = detections.acceptResult(
            attemptId,
            result,
            actorId(authentication),
            idempotencyKey
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PutMapping("/detection-attempts/{attempt_id}/failure")
    ResponseEntity<Map<String, Object>> submitDetectionFailure(
            @PathVariable("attempt_id") UUID attemptId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader("traceparent") String traceparent,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        traceId(traceparent);
        Map<String, Object> request = object(
            body,
            FAILURE_FIELDS,
            "执行失败请求"
        );
        Object retryable = request.get("retryable");
        if (!(retryable instanceof Boolean flag)) {
            throw new ContractValues.ContractInputViolation(
                "retryable 必须是布尔值"
            );
        }
        var response = detections.acceptFailure(
            attemptId,
            new DetectionFailureSubmission(
                text(request, "error_code", 1, 64),
                oneOf(
                    request,
                    "stage",
                    Set.of(
                        "DOWNLOAD", "DECODE", "PREPROCESS", "MODEL_LOAD",
                        "INFERENCE", "POSTPROCESS", "UPLOAD", "CALLBACK"
                    )
                ),
                flag,
                text(request, "message", 1, 512),
                instant(request, "occurred_at"),
                request
            ),
            actorId(authentication),
            idempotencyKey
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    private static DetectionResultSubmission result(
            Map<String, Object> body) {
        Map<String, Object> request = object(
            body,
            RESULT_FIELDS,
            "标准检测结果"
        );
        if (!"1.0".equals(text(request, "schema_version", 3, 3))
                || !"SUCCEEDED".equals(
                    text(request, "execution_status", 9, 9)
                )) {
            throw new ContractValues.ContractInputViolation(
                "结果模式或执行状态与 v1 契约不一致"
            );
        }
        OptionalDouble confidence;
        if (request.get("confidence") == null) {
            confidence = OptionalDouble.empty();
        } else {
            confidence = OptionalDouble.of(number(request, "confidence", 0, 1));
        }
        Map<String, Object> probabilities = object(
            request.get("class_probabilities"),
            PROBABILITY_FIELDS,
            "class_probabilities"
        );
        Map<String, Object> preprocess = object(
            request.get("preprocess"),
            PREPROCESS_FIELDS,
            "preprocess"
        );
        text(preprocess, "plugin_id", 1, 128);
        text(preprocess, "plugin_version", 1, 128);
        sha256(preprocess, "config_sha256");
        strings(preprocess, "warnings", 64, 256);
        Map<String, Object> algorithm = object(
            request.get("algorithm"),
            ALGORITHM_FIELDS,
            "algorithm"
        );
        text(algorithm, "plugin_id", 1, 128);
        text(algorithm, "plugin_version", 1, 128);
        Map<String, Object> timings = object(
            request.get("timings_ms"),
            TIMING_FIELDS,
            "timings_ms"
        );
        for (String field : TIMING_FIELDS) {
            number(timings, field, 0, Double.MAX_VALUE);
        }
        return new DetectionResultSubmission(
            uuid(request, "capture_id"),
            uuid(request, "detection_task_id"),
            uuid(request, "attempt_id"),
            "1.0",
            oneOf(
                request,
                "algorithm_outcome",
                Set.of("QUALIFIED", "UNQUALIFIED", "INCONCLUSIVE")
            ),
            confidence,
            number(probabilities, "qualified", 0, 1),
            number(probabilities, "unqualified", 0, 1),
            oneOf(
                preprocess,
                "quality_status",
                Set.of("OK", "WARNING", "REJECTED")
            ),
            text(algorithm, "model_version", 1, 128),
            sha256(algorithm, "model_sha256"),
            regions(request.get("regions")),
            artifacts(request.get("artifacts")),
            strings(request, "warnings", 64, 256),
            timings,
            request
        );
    }

    private static List<DetectionResultSubmission.Region> regions(Object value) {
        if (!(value instanceof List<?> raw) || raw.size() > 256) {
            throw new ContractValues.ContractInputViolation(
                "regions 数量不合法"
            );
        }
        List<DetectionResultSubmission.Region> result = new ArrayList<>();
        for (int index = 0; index < raw.size(); index++) {
            Map<String, Object> region = object(
                raw.get(index),
                REGION_FIELDS,
                "regions[" + index + "]"
            );
            Map<String, Object> scores = freeObject(
                region.get("scores"),
                16,
                "scores"
            );
            for (Object score : scores.values()) {
                if (!(score instanceof Number number)
                        || !Double.isFinite(number.doubleValue())
                        || number.doubleValue() < 0
                        || number.doubleValue() > 1) {
                    throw new ContractValues.ContractInputViolation(
                        "区域分数必须位于 0 到 1"
                    );
                }
            }
            Map<String, Object> attributes = freeObject(
                region.get("attributes"),
                32,
                "attributes"
            );
            for (Object attribute : attributes.values()) {
                if (attribute != null
                        && !(attribute instanceof String)
                        && !(attribute instanceof Number)
                        && !(attribute instanceof Boolean)) {
                    throw new ContractValues.ContractInputViolation(
                        "区域属性只允许标量值"
                    );
                }
            }
            String geometryType = oneOf(
                region,
                "geometry_type",
                Set.of("MASK_REF", "POLYGON", "BBOX", "POLAR_INTERVAL")
            );
            result.add(new DetectionResultSubmission.Region(
                Math.toIntExact(integer(region, "region_id", 1, Integer.MAX_VALUE)),
                oneOf(
                    region,
                    "coordinate_space",
                    Set.of("ORIGINAL", "MODEL", "POLAR")
                ),
                geometryType,
                geometry(region.get("geometry"), geometryType),
                scores,
                attributes
            ));
        }
        return List.copyOf(result);
    }

    private static List<DetectionResultSubmission.DerivedArtifact> artifacts(
            Object value) {
        if (!(value instanceof List<?> raw) || raw.size() > 32) {
            throw new ContractValues.ContractInputViolation(
                "artifacts 数量不合法"
            );
        }
        List<DetectionResultSubmission.DerivedArtifact> result =
            new ArrayList<>();
        for (int index = 0; index < raw.size(); index++) {
            Map<String, Object> artifact = object(
                raw.get(index),
                ARTIFACT_FIELDS,
                "artifacts[" + index + "]"
            );
            Map<String, Object> reference = freeObject(
                artifact.get("object"),
                6,
                "artifact.object"
            );
            if (!reference.keySet().containsAll(OBJECT_REQUIRED_FIELDS)
                    || reference.size() > 6
                    || (reference.size() == 6
                        && !reference.containsKey("object_version"))) {
                throw new ContractValues.ContractInputViolation(
                    "派生对象引用字段与 v1 契约不一致"
                );
            }
            result.add(new DetectionResultSubmission.DerivedArtifact(
                uuid(artifact, "image_id"),
                oneOf(
                    artifact,
                    "kind",
                    Set.of(
                        "RAW", "THUMBNAIL", "DEFECT_MASK", "HEATMAP",
                        "OVERLAY", "POLAR", "REVIEW_MASK"
                    )
                ),
                text(reference, "bucket", 1, 128),
                text(reference, "object_key", 1, 1024),
                reference.get("object_version") == null
                    ? ""
                    : text(reference, "object_version", 1, 256),
                sha256(reference, "sha256"),
                integer(reference, "size_bytes", 1, Long.MAX_VALUE),
                oneOf(
                    reference,
                    "media_type",
                    Set.of(
                        "image/png", "image/jpeg", "application/json",
                        "application/octet-stream"
                    )
                )
            ));
        }
        return List.copyOf(result);
    }

    private static Map<String, Object> geometry(
            Object value,
            String geometryType) {
        return switch (geometryType) {
            case "MASK_REF" -> {
                Map<String, Object> geometry = object(
                    value,
                    Set.of("image_id"),
                    "geometry"
                );
                uuid(geometry, "image_id");
                yield geometry;
            }
            case "BBOX" -> {
                Map<String, Object> geometry = object(
                    value,
                    Set.of("x", "y", "width", "height"),
                    "geometry"
                );
                for (String field : geometry.keySet()) {
                    number(geometry, field, 0, Double.MAX_VALUE);
                }
                yield geometry;
            }
            case "POLAR_INTERVAL" -> {
                Map<String, Object> geometry = object(
                    value,
                    Set.of(
                        "angle_start_degrees", "angle_end_degrees",
                        "radial_start", "radial_end"
                    ),
                    "geometry"
                );
                number(geometry, "angle_start_degrees", 0, 360);
                number(geometry, "angle_end_degrees", 0, 360);
                number(geometry, "radial_start", 0, 1);
                number(geometry, "radial_end", 0, 1);
                yield geometry;
            }
            case "POLYGON" -> polygon(value);
            default -> throw new IllegalStateException("未知几何类型");
        };
    }

    private static Map<String, Object> polygon(Object value) {
        Map<String, Object> geometry = object(
            value,
            Set.of("points"),
            "geometry"
        );
        if (!(geometry.get("points") instanceof List<?> points)
                || points.size() < 3
                || points.size() > 128) {
            throw new ContractValues.ContractInputViolation(
                "多边形点数量不合法"
            );
        }
        for (Object point : points) {
            if (!(point instanceof List<?> pair)
                    || pair.size() != 2
                    || !(pair.get(0) instanceof Number)
                    || !(pair.get(1) instanceof Number)) {
                throw new ContractValues.ContractInputViolation(
                    "多边形坐标不合法"
                );
            }
        }
        return geometry;
    }

    private static Map<String, Object> freeObject(
            Object value,
            int maximumProperties,
            String name) {
        if (!(value instanceof Map<?, ?> raw)
                || raw.size() > maximumProperties) {
            throw new ContractValues.ContractInputViolation(
                name + " 对象属性数量不合法"
            );
        }
        Map<String, Object> result = new LinkedHashMap<>();
        for (var entry : raw.entrySet()) {
            if (!(entry.getKey() instanceof String key)) {
                throw new ContractValues.ContractInputViolation(
                    name + " 包含非字符串键"
                );
            }
            result.put(key, entry.getValue());
        }
        return java.util.Collections.unmodifiableMap(result);
    }

    private static String traceId(String traceparent) {
        if (traceparent == null
                || !traceparent.matches(
                    "^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
                )) {
            throw new ContractValues.ContractInputViolation(
                "traceparent 格式不合法"
            );
        }
        return traceparent.substring(3, 35);
    }

    private static String actorId(Authentication authentication) {
        if (authentication == null
                || authentication.getName() == null
                || authentication.getName().isBlank()) {
            throw new DetectionIdentityViolation("推理服务身份缺失");
        }
        return authentication.getName();
    }

    public static final class DetectionIdentityViolation
            extends RuntimeException {
        DetectionIdentityViolation(String message) {
            super(message);
        }
    }
}
