package com.tooldefect.business.review.api;

import static com.tooldefect.business.shared.api.ContractValues.*;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

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

import com.tooldefect.business.review.application.ReviewRequestContext;
import com.tooldefect.business.review.application.ReviewSubmission;
import com.tooldefect.business.review.application.ReviewWorkspaceService;
import com.tooldefect.business.review.application.ReviewWorkflowService;
import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.api.ContractValues;

@RestController
@RequestMapping("/api/v1/review-tasks")
public final class ReviewController {
    private static final Set<String> ACTION_FIELDS = Set.of(
        "client_request_id", "reason"
    );
    private static final Set<String> SUBMISSION_FIELDS = Set.of(
        "decision",
        "reason_code",
        "comment",
        "defect_type_codes",
        "annotation_image_id",
        "client_submitted_at"
    );
    private static final Set<String> ANNOTATION_FIELDS = Set.of(
        "media_type", "size_bytes", "sha256", "width", "height"
    );
    private static final Set<String> COMPLETE_FIELDS = Set.of(
        "size_bytes", "sha256", "upload_receipt"
    );

    private final ReviewWorkflowService reviews;
    private final ReviewWorkspaceService workspaces;

    public ReviewController(
            ReviewWorkflowService reviews,
            ReviewWorkspaceService workspaces) {
        this.reviews = java.util.Objects.requireNonNull(reviews);
        this.workspaces = java.util.Objects.requireNonNull(workspaces);
    }

    @GetMapping
    Map<String, Object> listReviewTasks(
            @RequestParam(value = "cursor", required = false) String cursor,
            @RequestParam(value = "page_size", defaultValue = "50") int pageSize,
            @RequestParam(value = "status", required = false) String status,
            @RequestHeader(
                value = "X-Request-ID",
                required = false
            ) String requestId,
            @RequestHeader(
                value = "traceparent",
                required = false
            ) String traceparent,
            Authentication authentication) {
        return reviews.list(
            context(authentication, requestId, traceparent),
            cursor,
            pageSize,
            status
        );
    }

    @GetMapping("/{review_task_id}")
    Map<String, Object> getReviewWorkspace(
            @PathVariable("review_task_id") UUID reviewTaskId,
            @RequestHeader(
                value = "X-Request-ID",
                required = false
            ) String requestId,
            @RequestHeader(
                value = "traceparent",
                required = false
            ) String traceparent,
            Authentication authentication) {
        return workspaces.get(
            reviewTaskId,
            context(authentication, requestId, traceparent)
        );
    }

    @PostMapping("/{review_task_id}/claim")
    ResponseEntity<Map<String, Object>> claimReviewTask(
            @PathVariable("review_task_id") UUID reviewTaskId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader("If-Match") String ifMatch,
            @RequestHeader(
                value = "X-Request-ID",
                required = false
            ) String requestId,
            @RequestHeader(
                value = "traceparent",
                required = false
            ) String traceparent,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        Map<String, Object> request = action(body);
        var response = reviews.claim(
            reviewTaskId,
            version(ifMatch),
            idempotencyKey,
            request,
            context(authentication, requestId, traceparent)
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/{review_task_id}/release")
    ResponseEntity<Map<String, Object>> releaseReviewTask(
            @PathVariable("review_task_id") UUID reviewTaskId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader("If-Match") String ifMatch,
            @RequestHeader(
                value = "X-Request-ID",
                required = false
            ) String requestId,
            @RequestHeader(
                value = "traceparent",
                required = false
            ) String traceparent,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        Map<String, Object> request = action(body);
        var response = reviews.release(
            reviewTaskId,
            version(ifMatch),
            idempotencyKey,
            request,
            context(authentication, requestId, traceparent)
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/{review_task_id}/submissions")
    ResponseEntity<Map<String, Object>> submitReview(
            @PathVariable("review_task_id") UUID reviewTaskId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader("If-Match") String ifMatch,
            @RequestHeader(
                value = "X-Request-ID",
                required = false
            ) String requestId,
            @RequestHeader(
                value = "traceparent",
                required = false
            ) String traceparent,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        Map<String, Object> request = object(
            body,
            SUBMISSION_FIELDS,
            "复核提交请求"
        );
        UUID annotationImageId = nullableUuid(
            request.get("annotation_image_id")
        );
        ReviewSubmission submission = new ReviewSubmission(
            oneOf(request, "decision", Set.of("PASS", "FAIL", "HOLD")),
            text(request, "reason_code", 1, 64),
            text(request, "comment", 0, 2000),
            strings(request, "defect_type_codes", 32, 64),
            annotationImageId,
            instant(request, "client_submitted_at")
        );
        var response = reviews.submit(
            reviewTaskId,
            version(ifMatch),
            idempotencyKey,
            request,
            submission,
            context(authentication, requestId, traceparent)
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/{review_task_id}/annotation-upload-ticket")
    ResponseEntity<Map<String, Object>> createAnnotationUploadTicket(
            @PathVariable("review_task_id") UUID reviewTaskId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader(
                value = "X-Request-ID",
                required = false
            ) String requestId,
            @RequestHeader(
                value = "traceparent",
                required = false
            ) String traceparent,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        Map<String, Object> request = object(
            body,
            ANNOTATION_FIELDS,
            "人工掩膜上传请求"
        );
        oneOf(request, "media_type", Set.of("image/png"));
        var response = reviews.issueAnnotationUpload(
            reviewTaskId,
            idempotencyKey,
            request,
            integer(request, "size_bytes", 1, Long.MAX_VALUE),
            sha256(request, "sha256"),
            Math.toIntExact(integer(request, "width", 1, 32768)),
            Math.toIntExact(integer(request, "height", 1, 32768)),
            context(authentication, requestId, traceparent)
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/{review_task_id}/annotations/{image_id}/complete")
    ResponseEntity<Map<String, Object>> completeReviewAnnotation(
            @PathVariable("review_task_id") UUID reviewTaskId,
            @PathVariable("image_id") UUID imageId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestHeader(
                value = "X-Request-ID",
                required = false
            ) String requestId,
            @RequestHeader(
                value = "traceparent",
                required = false
            ) String traceparent,
            @RequestBody Map<String, Object> body,
            Authentication authentication) {
        Map<String, Object> request = object(
            body,
            COMPLETE_FIELDS,
            "人工掩膜确认请求"
        );
        var response = reviews.confirmAnnotation(
            reviewTaskId,
            imageId,
            idempotencyKey,
            request,
            integer(request, "size_bytes", 1, Long.MAX_VALUE),
            sha256(request, "sha256"),
            text(request, "upload_receipt", 1, 512),
            context(authentication, requestId, traceparent)
        );
        return ResponseEntity.status(response.status()).body(response.body());
    }

    private static Map<String, Object> action(Map<String, Object> body) {
        Map<String, Object> request = object(
            body,
            ACTION_FIELDS,
            "复核动作请求"
        );
        uuid(request, "client_request_id");
        if (request.containsKey("reason") && request.get("reason") != null) {
            text(request, "reason", 1, 512);
        }
        return request;
    }

    private static long version(String value) {
        if (value == null || !value.matches("\"?[0-9]+\"?")) {
            throw new ContractValues.ContractInputViolation(
                "If-Match 不符合复核契约"
            );
        }
        String normalized = value.replace("\"", "");
        try {
            return Long.parseLong(normalized);
        } catch (NumberFormatException invalid) {
            throw new ContractValues.ContractInputViolation(
                "If-Match 超出版本范围",
                invalid
            );
        }
    }

    private static UUID nullableUuid(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return UUID.fromString(String.valueOf(value));
        } catch (IllegalArgumentException invalid) {
            throw new ContractValues.ContractInputViolation(
                "annotation_image_id 不是合法 UUID",
                invalid
            );
        }
    }

    private static ReviewRequestContext context(
            Authentication authentication,
            String requestId,
            String traceparent) {
        if (authentication == null || !authentication.isAuthenticated()) {
            throw new ContractValues.ContractInputViolation(
                "复核操作缺少认证身份"
            );
        }
        String actorId = authentication.getName();
        if (authentication.getPrincipal() instanceof Jwt jwt) {
            actorId = jwt.getSubject();
        }
        String stableRequestId = requestId;
        if (stableRequestId == null
                || stableRequestId.isBlank()
                || stableRequestId.length() > 128) {
            stableRequestId = UUID.randomUUID().toString();
        }
        return new ReviewRequestContext(
            actorId,
            stableRequestId,
            traceId(traceparent, stableRequestId)
        );
    }

    private static String traceId(String traceparent, String requestId) {
        if (traceparent != null
                && traceparent.matches(
                    "^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"
                )) {
            return traceparent.split("-")[1];
        }
        Map<String, Object> input = new LinkedHashMap<>();
        input.put("request_id", requestId);
        return CanonicalJson.sha256(input).substring(0, 32);
    }
}
