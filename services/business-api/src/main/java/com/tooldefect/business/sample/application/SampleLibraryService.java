package com.tooldefect.business.sample.application;

import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.audit.domain.AuditRecord;
import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.OutboxRepository;
import com.tooldefect.business.shared.messaging.OutboxEvent;
import com.tooldefect.business.storage.application.ObjectStoragePort;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** R7 业务用例：只追加管理员事实，导出由独立 worker 执行。 */
public class SampleLibraryService {
    private static final Set<String> FEEDBACK_LABELS = Set.of(
        "CORRECT_DETECTION", "FALSE_POSITIVE", "FALSE_NEGATIVE",
        "LOCALIZATION_INACCURATE", "IMAGE_UNUSABLE", "UNCONFIRMED");
    private static final Set<String> CANDIDATE_DECISIONS = Set.of("INCLUDE", "EXCLUDE");
    private static final Set<String> ITEM_STATUSES = Set.of(
        "READY", "QUEUED", "PROCESSING", "COMPLETED", "QUALITY_REJECTED", "FAILED");
    private final SampleLibraryRepository repository;
    private final ObjectStoragePort storage;
    private final IdempotencyService idempotency;
    private final AuditTrail audit;
    private final OutboxRepository outbox;
    private final SampleLibrarySettings settings;
    private final Clock clock;
    private final ObjectMapper json;
    private final SecureRandom random;

    public SampleLibraryService(
            SampleLibraryRepository repository,
            ObjectStoragePort storage,
            IdempotencyService idempotency,
            AuditTrail audit,
            OutboxRepository outbox,
            SampleLibrarySettings settings,
            Clock clock,
            ObjectMapper json,
            SecureRandom random) {
        this.repository = java.util.Objects.requireNonNull(repository);
        this.storage = java.util.Objects.requireNonNull(storage);
        this.idempotency = java.util.Objects.requireNonNull(idempotency);
        this.audit = java.util.Objects.requireNonNull(audit);
        this.outbox = outbox;
        this.settings = java.util.Objects.requireNonNull(settings);
        this.clock = java.util.Objects.requireNonNull(clock);
        this.json = java.util.Objects.requireNonNull(json);
        this.random = java.util.Objects.requireNonNull(random);
    }

    public Map<String, Object> listAdminDetectionItems(
            String label, String status, String usageStage, String cursor) {
        requireEnabled();
        if (label != null && !FEEDBACK_LABELS.contains(label)) {
            throw violation(SampleViolation.Kind.INTEGRITY, "管理员反馈标签不合法");
        }
        if (status != null && !ITEM_STATUSES.contains(status)) {
            throw violation(SampleViolation.Kind.INTEGRITY, "检测图片项状态不合法");
        }
        List<SampleLibraryRepository.AdminDetectionItem> rows =
            repository.listAdminDetectionItems(label, status, usageStage, cursor, 50);
        boolean hasNext = rows.size() > 50;
        List<SampleLibraryRepository.AdminDetectionItem> page = hasNext
            ? rows.subList(0, 50) : rows;
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("items", page.stream().map(SampleLibraryService::adminItem).toList());
        if (hasNext) {
            var last = page.getLast();
            response.put("next_cursor", SampleCursor.encode(last.createdAt(), last.batchItemId()));
        }
        return response;
    }

    @Transactional
    public IdempotencyService.Response saveAdminFeedback(
            UUID actor, UUID itemId, String key, String label, String note,
            UUID sourceReviewRecordId, UUID supersedesFeedbackId,
            Map<String, Object> request, String requestId, String traceId) {
        requireEnabled();
        if (!FEEDBACK_LABELS.contains(label)) {
            throw violation(SampleViolation.Kind.INTEGRITY, "管理员反馈标签不合法");
        }
        return idempotency.execute("v2.sample.admin-feedback:" + itemId,
            actor.toString(), key, request, () -> {
                UUID feedbackId = UUID.randomUUID();
                var value = repository.appendAdminFeedback(feedbackId, itemId, actor, label,
                    note, sourceReviewRecordId, supersedesFeedbackId, key);
                audit(actor, "R7_ADMIN_FEEDBACK_CREATE", "detection_item", itemId,
                    Map.of("label", value.label(), "revision", value.revision()),
                    requestId, traceId);
                return new IdempotencyService.Response(201, feedback(value));
            });
    }

    @Transactional
    public IdempotencyService.Response createCandidate(
            UUID actor, UUID itemId, UUID feedbackId, String key,
            Map<String, Object> request, String requestId, String traceId) {
        requireEnabled();
        return idempotency.execute("v2.sample.candidate-create", actor.toString(), key,
            request, () -> {
                var value = repository.createCandidate(UUID.randomUUID(), itemId, feedbackId);
                audit(actor, "R7_SAMPLE_CANDIDATE_CREATE", "sample_candidate",
                    value.candidateId(), Map.of("feedback_id", value.feedbackId()), requestId, traceId);
                return new IdempotencyService.Response(201, candidate(value));
            });
    }

    public Map<String, Object> listCandidates(String status, String cursor) {
        requireEnabled();
        if (status != null && !Set.of("PENDING", "INCLUDED", "EXCLUDED", "EXPORTED").contains(status)) {
            throw violation(SampleViolation.Kind.INTEGRITY, "样本候选状态不合法");
        }
        List<SampleLibraryRepository.Candidate> rows = repository.listCandidates(status, cursor, 50);
        boolean hasNext = rows.size() > 50;
        List<SampleLibraryRepository.Candidate> page = hasNext ? rows.subList(0, 50) : rows;
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("items", page.stream().map(this::candidate).toList());
        if (hasNext) {
            var last = page.getLast();
            response.put("next_cursor", SampleCursor.encode(last.createdAt(), last.candidateId()));
        }
        return response;
    }

    @Transactional
    public IdempotencyService.Response decideCandidate(
            UUID actor, UUID candidateId, String key, String decision, String note,
            UUID supersedesDecisionId, Map<String, Object> request,
            String requestId, String traceId) {
        requireEnabled();
        if (!CANDIDATE_DECISIONS.contains(decision)) {
            throw violation(SampleViolation.Kind.INTEGRITY, "候选决策不合法");
        }
        return idempotency.execute("v2.sample.candidate-decision:" + candidateId,
            actor.toString(), key, request, () -> {
                var value = repository.decideCandidate(candidateId, actor, decision, note,
                    supersedesDecisionId);
                audit(actor, "R7_SAMPLE_CANDIDATE_DECIDE", "sample_candidate", candidateId,
                    Map.of("decision", decision), requestId, traceId);
                return new IdempotencyService.Response(200, candidate(value));
            });
    }

    @Transactional
    public IdempotencyService.Response createExport(
            UUID actor, String key, List<UUID> candidateIds, Map<String, String> filterSnapshot,
            Map<String, Object> request, String requestId, String traceId) {
        requireEnabled();
        if (outbox == null) {
            throw violation(SampleViolation.Kind.DISABLED, "样本导出发件箱未配置");
        }
        if (candidateIds.isEmpty() || candidateIds.size() > settings.maximumCandidates()
                || candidateIds.stream().distinct().count() != candidateIds.size()) {
            throw violation(SampleViolation.Kind.INTEGRITY, "样本导出候选数量或重复项不合法");
        }
        return idempotency.execute("v2.sample.export-create", actor.toString(), key, request, () -> {
            UUID jobId = UUID.randomUUID();
            String packageKey = settings.objectPrefix() + "/" + jobId + "/package.zip";
            Instant createdAt = Instant.now(clock);
            Instant expiresAt = createdAt.plus(settings.packageRetention());
            var job = repository.createExportJob(jobId, actor, candidateIds, filterSnapshot,
                settings.objectBucket(), packageKey, expiresAt);
            UUID messageId = UUID.nameUUIDFromBytes(
                ("r7-export-message:" + jobId).getBytes(StandardCharsets.UTF_8));
            UUID eventId = UUID.nameUUIDFromBytes(
                ("r7-export-outbox:" + jobId).getBytes(StandardCharsets.UTF_8));
            String traceparent = "00-" + traceId + "-"
                + CanonicalJson.sha256(messageId.toString()).substring(0, 16) + "-01";
            Map<String, Object> target = new LinkedHashMap<>();
            target.put("bucket", settings.objectBucket());
            target.put("object_key", packageKey);
            target.put("media_type", "application/zip");
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("message_id", messageId.toString());
            payload.put("occurred_at", createdAt.toString());
            payload.put("idempotency_key", key);
            payload.put("traceparent", traceparent);
            payload.put("sample_export_job_id", jobId.toString());
            payload.put("candidate_ids", candidateIds.stream().map(UUID::toString).toList());
            payload.put("target_object", target);
            outbox.append(OutboxEvent.pending(eventId, "sample_export_job", jobId,
                "tool_defect.sample.export.requested.v2", "sample.export.requested.v2",
                CanonicalJson.encode(payload), createdAt));
            audit(actor, "R7_SAMPLE_EXPORT_CREATE", "sample_export_job", jobId,
                Map.of("candidate_count", candidateIds.size()), requestId, traceId);
            return new IdempotencyService.Response(202, exportJob(job));
        });
    }

    public Map<String, Object> getExport(UUID jobId) {
        requireEnabled();
        return exportJob(repository.findExportJob(jobId)
            .orElseThrow(() -> violation(SampleViolation.Kind.NOT_FOUND, "样本导出作业不存在")));
    }

    @Transactional
    public IdempotencyService.Response recordExternalReceipt(
            UUID actor, UUID jobId, String key, String receiverName,
            String externalReference, String receiptNote, Map<String, Object> request,
            String requestId, String traceId) {
        requireEnabled();
        if (receiverName == null || receiverName.isBlank()) {
            throw violation(SampleViolation.Kind.INTEGRITY, "外部接收方不能为空");
        }
        return idempotency.execute("v2.sample.external-receipt:" + jobId,
            actor.toString(), key, request, () -> {
                UUID receiptId = UUID.randomUUID();
                var receipt = repository.appendExternalReceipt(receiptId, jobId, receiverName,
                    externalReference, receiptNote, actor);
                audit(actor, "R7_SAMPLE_EXTERNAL_RECEIPT_CREATE", "sample_export_job", jobId,
                    Map.of("receipt_id", receipt.receiptId(), "receiver_name", receiverName),
                    requestId, traceId);
                return new IdempotencyService.Response(201, externalReceipt(receipt));
            });
    }

    @Transactional
    public IdempotencyService.Response issueDownloadTicket(
            UUID actor, UUID jobId, String key, Map<String, Object> request,
            String requestId, String traceId) {
        requireEnabled();
        return idempotency.execute("v2.sample.download-ticket:" + jobId,
            actor.toString(), key, request, () -> {
                var job = repository.findExportJob(jobId)
                    .orElseThrow(() -> violation(SampleViolation.Kind.NOT_FOUND, "样本导出作业不存在"));
                if (!("SUCCEEDED".equals(job.status()) || "FAILED".equals(job.status()))
                        || job.packageReference() == null) {
                    throw violation(SampleViolation.Kind.CONFLICT, "导出作业尚未形成可下载对象");
                }
                Instant issuedAt = Instant.now(clock);
                Instant expiresAt = issuedAt.plus(settings.ticketTtl());
                String token = randomToken();
                String tokenHash = CanonicalJson.sha256(token);
                String downloadUrl = storage.authorizeRead(
                    job.packageReference().bucket(), job.packageReference().objectKey(),
                    settings.ticketTtl()).toString();
                UUID ticketId = UUID.randomUUID();
                var ticket = repository.issueDownloadTicket(ticketId, jobId, tokenHash, actor,
                    issuedAt, expiresAt, downloadUrl, requestId);
                audit(actor, "R7_SAMPLE_DOWNLOAD_TICKET_ISSUE", "sample_export_job", jobId,
                    Map.of("ticket_id", ticketId), requestId, traceId);
                return new IdempotencyService.Response(200, Map.of(
                    "ticket_id", ticket.ticketId().toString(),
                    "download_url", ticket.downloadUrl(),
                    "expires_at", ticket.expiresAt().toString()));
            });
    }

    public void cleanupExpired(String requestId, String traceId) {
        if (!settings.enabled()) {
            return;
        }
        repository.expireDownloadTickets(Instant.now(clock), requestId);
    }

    private void requireEnabled() {
        if (!settings.enabled()) {
            throw violation(SampleViolation.Kind.DISABLED, "R7 样本导出能力未启用");
        }
    }

    private String randomToken() {
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private static Map<String, Object> adminItem(SampleLibraryRepository.AdminDetectionItem item) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("batch_item_id", item.batchItemId().toString());
        result.put("batch_id", item.batchId().toString());
        result.put("status", item.itemStatus());
        result.put("algorithm_outcome", item.algorithmOutcome());
        result.put("employee_feedback", item.employeeDecision());
        result.put("usage_stage", item.usageStage());
        result.put("image", objectReference(item.image()));
        result.put("created_at", item.createdAt().toString());
        result.put("updated_at", item.updatedAt().toString());
        if (item.latestFeedback() != null) {
            result.put("latest_admin_feedback", feedback(item.latestFeedback()));
        }
        return result;
    }

    private static Map<String, Object> feedback(SampleLibraryRepository.FeedbackRecord value) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("feedback_id", value.feedbackId().toString());
        result.put("batch_item_id", value.batchItemId().toString());
        result.put("label", value.label());
        if (value.note() != null) result.put("note", value.note());
        if (value.sourceReviewRecordId() != null) {
            result.put("source_review_record_id", value.sourceReviewRecordId().toString());
        }
        if (value.supersedesFeedbackId() != null) {
            result.put("supersedes_feedback_id", value.supersedesFeedbackId().toString());
        }
        result.put("revision", value.revision());
        result.put("submitted_by", value.submittedBy().toString());
        result.put("submitted_at", value.submittedAt().toString());
        return result;
    }

    private Map<String, Object> candidate(SampleLibraryRepository.Candidate value) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("sample_candidate_id", value.candidateId().toString());
        result.put("batch_item_id", value.batchItemId().toString());
        result.put("feedback_id", value.feedbackId().toString());
        result.put("status", value.status());
        if (value.decisionNote() != null) result.put("decision_note", value.decisionNote());
        result.put("source_snapshot", sourceSnapshot(value.sourceSnapshot()));
        if (value.latestDecisionId() != null) result.put("latest_decision_id", value.latestDecisionId().toString());
        if (value.exportJobId() != null) result.put("export_job_id", value.exportJobId().toString());
        result.put("created_at", value.createdAt().toString());
        return result;
    }

    private Map<String, Object> exportJob(SampleLibraryRepository.ExportJob value) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("sample_export_job_id", value.jobId().toString());
        result.put("filter_snapshot", value.filterSnapshot());
        result.put("candidate_count", value.candidateCount());
        result.put("exported_count", value.exportedCount());
        result.put("failed_count", value.failedCount());
        result.put("status", value.status());
        if (value.packageReference() != null) result.put("package", objectReference(value.packageReference()));
        if (value.manifestReference() != null) result.put("manifest", objectReference(value.manifestReference()));
        result.put("failed_candidate_ids", value.failedCandidateIds().stream().map(UUID::toString).toList());
        result.put("created_at", value.createdAt().toString());
        if (value.expiresAt() != null) result.put("expires_at", value.expiresAt().toString());
        result.put("external_receipts", value.externalReceipts().stream()
            .map(SampleLibraryService::externalReceipt).toList());
        return result;
    }

    private static Map<String, Object> externalReceipt(
            SampleLibraryRepository.ExternalReceipt value) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("receipt_id", value.receiptId().toString());
        result.put("sample_export_job_id", value.jobId().toString());
        result.put("receiver_name", value.receiverName());
        if (value.externalReference() != null) {
            result.put("external_reference", value.externalReference());
        }
        if (value.receiptNote() != null) {
            result.put("receipt_note", value.receiptNote());
        }
        result.put("recorded_by", value.recordedBy().toString());
        result.put("recorded_at", value.recordedAt().toString());
        return result;
    }

    private Object sourceSnapshot(String raw) {
        try {
            return json.readTree(raw);
        } catch (RuntimeException invalid) {
            throw violation(SampleViolation.Kind.HOLD, "候选来源快照无法解析");
        }
    }

    private static Map<String, Object> objectReference(SampleLibraryRepository.ObjectReference value) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("bucket", value.bucket());
        result.put("object_key", value.objectKey());
        result.put("sha256", value.sha256());
        result.put("size_bytes", value.sizeBytes());
        result.put("media_type", value.mediaType());
        if (value.objectVersion() != null) result.put("object_version", value.objectVersion());
        return result;
    }

    private void audit(
            UUID actor, String action, String resourceType, UUID resourceId,
            Map<String, Object> after, String requestId, String traceId) {
        // 仅把稳定摘要写入审计，原图、结果 JSON 和令牌绝不进入数据库审计正文。
        String digest = CanonicalJson.sha256(after);
        audit.append(new AuditRecord(UUID.randomUUID(), Instant.now(clock), "USER",
            actor.toString(), action, resourceType, resourceId.toString(), null,
            digest, null, requestId, traceId, "SUCCESS", null));
    }

    private static SampleViolation violation(SampleViolation.Kind kind, String message) {
        return new SampleViolation(kind, message);
    }
}
