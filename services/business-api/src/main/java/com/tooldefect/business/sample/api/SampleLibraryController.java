package com.tooldefect.business.sample.api;

import static com.tooldefect.business.shared.api.ContractValues.objectV2;
import static com.tooldefect.business.shared.api.ContractValues.oneOf;
import static com.tooldefect.business.shared.api.ContractValues.strings;
import static com.tooldefect.business.shared.api.ContractValues.text;
import static com.tooldefect.business.shared.api.ContractValues.uuid;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.tooldefect.business.identity.application.LocalIdentity;
import com.tooldefect.business.sample.application.SampleLibraryService;
import com.tooldefect.business.sample.application.SampleViolation;
import com.tooldefect.business.shared.application.IdempotencyService;

@RestController
@RequestMapping("/api/v2")
@ConditionalOnProperty(name = {"td.sample-export.enabled", "td.storage.enabled"}, havingValue = "true")
public final class SampleLibraryController {
    private static final Set<String> FEEDBACK_FIELDS = Set.of(
        "label", "note", "source_review_record_id", "supersedes_feedback_id");
    private static final Set<String> CANDIDATE_FIELDS = Set.of("batch_item_id", "feedback_id");
    private static final Set<String> DECISION_FIELDS = Set.of(
        "decision", "note", "supersedes_decision_id");
    private static final Set<String> EXPORT_FIELDS = Set.of("candidate_ids", "filter_snapshot");
    private static final Set<String> RECEIPT_FIELDS = Set.of(
        "receiver_name", "external_reference", "receipt_note");
    private static final Set<String> EMPTY_FIELDS = Set.of();
    private static final Set<String> LABELS = Set.of(
        "CORRECT_DETECTION", "FALSE_POSITIVE", "FALSE_NEGATIVE",
        "LOCALIZATION_INACCURATE", "IMAGE_UNUSABLE", "UNCONFIRMED");
    private static final Set<String> STAGES = Set.of(
        "NEW_BLADE", "AFTER_ONE_WHEEL", "AFTER_TWO_WHEELS", "AFTER_THREE_WHEELS",
        "OTHER", "UNSPECIFIED");
    private final SampleLibraryService service;

    public SampleLibraryController(SampleLibraryService service) {
        this.service = java.util.Objects.requireNonNull(service);
    }

    @GetMapping("/admin/detection-items")
    Map<String, Object> listAdminDetectionItems(
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) String label,
            @RequestParam(required = false) String status,
            @RequestParam(name = "usage_stage", required = false) String usageStage,
            Authentication authentication) {
        identity(authentication);
        if (label != null && !LABELS.contains(label)) {
            throw new SampleViolation(SampleViolation.Kind.INTEGRITY, "管理员反馈标签不合法");
        }
        if (usageStage != null && !STAGES.contains(usageStage)) {
            throw new SampleViolation(SampleViolation.Kind.INTEGRITY, "使用阶段不合法");
        }
        return service.listAdminDetectionItems(label, status, usageStage, cursor);
    }

    @PostMapping("/admin/detection-items/{item_id}/feedback")
    ResponseEntity<Map<String, Object>> createAdminFeedback(
            @PathVariable("item_id") UUID itemId,
            @RequestHeader("Idempotency-Key") String key,
            @RequestBody Map<String, Object> body,
            Authentication authentication,
            HttpServletRequest servlet) {
        Map<String, Object> request = objectV2(body, FEEDBACK_FIELDS, Set.of("label"), "管理员反馈请求");
        UUID sourceReview = optionalUuid(request, "source_review_record_id");
        UUID supersedes = optionalUuid(request, "supersedes_feedback_id");
        String note = request.containsKey("note") ? text(request, "note", 0, 2000) : null;
        var response = service.saveAdminFeedback(identity(authentication).userId(), itemId, key,
            oneOf(request, "label", LABELS), note, sourceReview, supersedes, request,
            requestId(servlet), traceId(servlet));
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @GetMapping("/sample-candidates")
    Map<String, Object> listCandidates(
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) String status,
            Authentication authentication) {
        identity(authentication);
        return service.listCandidates(status, cursor);
    }

    @PostMapping("/sample-candidates")
    ResponseEntity<Map<String, Object>> createCandidate(
            @RequestHeader("Idempotency-Key") String key,
            @RequestBody Map<String, Object> body,
            Authentication authentication,
            HttpServletRequest servlet) {
        Map<String, Object> request = objectV2(body, CANDIDATE_FIELDS, CANDIDATE_FIELDS, "样本候选请求");
        var response = service.createCandidate(identity(authentication).userId(),
            uuid(request, "batch_item_id"), uuid(request, "feedback_id"), key, request,
            requestId(servlet), traceId(servlet));
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/sample-candidates/{candidate_id}/decision")
    ResponseEntity<Map<String, Object>> decideCandidate(
            @PathVariable("candidate_id") UUID candidateId,
            @RequestHeader("Idempotency-Key") String key,
            @RequestBody Map<String, Object> body,
            Authentication authentication,
            HttpServletRequest servlet) {
        Map<String, Object> request = objectV2(body, DECISION_FIELDS, Set.of("decision"), "样本候选决策请求");
        UUID supersedes = optionalUuid(request, "supersedes_decision_id");
        String note = request.containsKey("note") ? text(request, "note", 0, 1000) : null;
        var response = service.decideCandidate(identity(authentication).userId(), candidateId, key,
            oneOf(request, "decision", Set.of("INCLUDE", "EXCLUDE")), note, supersedes,
            request, requestId(servlet), traceId(servlet));
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/sample-exports")
    ResponseEntity<Map<String, Object>> createExport(
            @RequestHeader("Idempotency-Key") String key,
            @RequestBody Map<String, Object> body,
            Authentication authentication,
            HttpServletRequest servlet) {
        Map<String, Object> request = objectV2(body, EXPORT_FIELDS, Set.of("candidate_ids"), "样本导出请求");
        List<UUID> candidateIds = new ArrayList<>();
        for (String value : strings(request, "candidate_ids", 10_000, 36)) {
            try {
                candidateIds.add(UUID.fromString(value));
            } catch (IllegalArgumentException invalid) {
                throw new SampleViolation(SampleViolation.Kind.INTEGRITY, "候选标识不合法");
            }
        }
        Map<String, String> filterSnapshot = filterSnapshot(request);
        var response = service.createExport(identity(authentication).userId(), key, List.copyOf(candidateIds),
            filterSnapshot, request, requestId(servlet), traceId(servlet));
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @GetMapping("/sample-exports/{export_job_id}")
    Map<String, Object> getExport(
            @PathVariable("export_job_id") UUID jobId,
            Authentication authentication) {
        identity(authentication);
        return service.getExport(jobId);
    }

    @PostMapping("/sample-exports/{export_job_id}/download-ticket")
    ResponseEntity<Map<String, Object>> createDownloadTicket(
            @PathVariable("export_job_id") UUID jobId,
            @RequestHeader("Idempotency-Key") String key,
            @RequestBody Map<String, Object> body,
            Authentication authentication,
            HttpServletRequest servlet) {
        Map<String, Object> request = objectV2(body, EMPTY_FIELDS, EMPTY_FIELDS, "下载票据请求");
        var response = service.issueDownloadTicket(identity(authentication).userId(), jobId, key,
            request, requestId(servlet), traceId(servlet));
        return ResponseEntity.status(response.status()).body(response.body());
    }

    @PostMapping("/sample-exports/{export_job_id}/external-receipts")
    ResponseEntity<Map<String, Object>> createExternalReceipt(
            @PathVariable("export_job_id") UUID jobId,
            @RequestHeader("Idempotency-Key") String key,
            @RequestBody Map<String, Object> body,
            Authentication authentication,
            HttpServletRequest servlet) {
        Map<String, Object> request = objectV2(body, RECEIPT_FIELDS,
            Set.of("receiver_name"), "外部接收回执请求");
        String receiverName = text(request, "receiver_name", 1, 256);
        String externalReference = request.containsKey("external_reference")
            ? text(request, "external_reference", 0, 512) : null;
        String receiptNote = request.containsKey("receipt_note")
            ? text(request, "receipt_note", 0, 2000) : null;
        var response = service.recordExternalReceipt(identity(authentication).userId(), jobId, key,
            receiverName, externalReference, receiptNote, request,
            requestId(servlet), traceId(servlet));
        return ResponseEntity.status(response.status()).body(response.body());
    }

    private static Map<String, String> filterSnapshot(Map<String, Object> request) {
        Object raw = request.get("filter_snapshot");
        if (raw == null) return Map.of();
        if (!(raw instanceof Map<?, ?> values) || values.size() > 32) {
            throw new SampleViolation(SampleViolation.Kind.INTEGRITY, "筛选快照必须是文本对象");
        }
        Map<String, String> result = new LinkedHashMap<>();
        for (var entry : values.entrySet()) {
            if (!(entry.getKey() instanceof String key)
                    || !(entry.getValue() instanceof String value)
                    || key.length() > 64 || value.length() > 256) {
                throw new SampleViolation(SampleViolation.Kind.INTEGRITY, "筛选快照包含非法值");
            }
            result.put(key, value);
        }
        return Map.copyOf(result);
    }

    private static UUID optionalUuid(Map<String, Object> request, String field) {
        return request.containsKey(field) ? uuid(request, field) : null;
    }

    private static LocalIdentity identity(Authentication authentication) {
        if (authentication == null || !(authentication.getPrincipal() instanceof LocalIdentity value)) {
            throw new SampleViolation(SampleViolation.Kind.CONFLICT, "缺少人员身份");
        }
        return value;
    }

    private static String requestId(HttpServletRequest request) {
        try {
            return UUID.fromString(request.getHeader("X-Request-Id")).toString();
        } catch (RuntimeException invalid) {
            return UUID.randomUUID().toString();
        }
    }

    private static String traceId(HttpServletRequest request) {
        String value = request.getHeader("traceparent");
        return value != null && value.matches("^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$")
            ? value.substring(3, 35)
            : UUID.randomUUID().toString().replace("-", "");
    }
}
