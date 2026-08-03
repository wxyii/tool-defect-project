package com.tooldefect.business.sample.application;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/** R7 样本库事实与状态投影的持久化边界。 */
public interface SampleLibraryRepository {
    List<AdminDetectionItem> listAdminDetectionItems(
            String label, String status, String usageStage, String cursor, int limit);

    FeedbackRecord appendAdminFeedback(
            UUID feedbackId, UUID itemId, UUID actorId, String label, String note,
            UUID sourceReviewRecordId, UUID supersedesFeedbackId, String idempotencyKey);

    Candidate createCandidate(UUID candidateId, UUID itemId, UUID feedbackId);

    List<Candidate> listCandidates(String status, String cursor, int limit);

    Candidate decideCandidate(
            UUID candidateId, UUID actorId, String decision, String note,
            UUID supersedesDecisionId);

    ExportJob createExportJob(
            UUID jobId, UUID actorId, List<UUID> candidateIds,
            Map<String, String> filterSnapshot, String packageBucket, String packageKey,
            Instant expiresAt);

    Optional<ExportJob> findExportJob(UUID jobId);

    ExternalReceipt appendExternalReceipt(
            UUID receiptId, UUID jobId, String receiverName,
            String externalReference, String receiptNote, UUID actorId);

    void applyExportCompleted(
            UUID jobId, ObjectReference packageReference, ObjectReference manifestReference,
            int exportedCount, List<UUID> failedCandidateIds);

    DownloadTicket issueDownloadTicket(
            UUID ticketId, UUID jobId, String tokenHash, UUID actorId,
            Instant issuedAt, Instant expiresAt, String downloadUrl, String requestId);

    void expireDownloadTickets(Instant now, String requestId);

    record ObjectReference(
            String bucket, String objectKey, String objectVersion,
            String sha256, long sizeBytes, String mediaType) {}

    record FeedbackRecord(
            UUID feedbackId, UUID batchItemId, String label, String note,
            UUID sourceReviewRecordId, UUID supersedesFeedbackId, int revision,
            UUID submittedBy, Instant submittedAt) {}

    record AdminDetectionItem(
            UUID batchItemId, UUID batchId, ObjectReference image,
            String itemStatus, String algorithmOutcome, String employeeDecision,
            String usageStage, FeedbackRecord latestFeedback,
            Instant createdAt, Instant updatedAt) {}

    record Candidate(
            UUID candidateId, UUID batchItemId, UUID feedbackId, String status,
            String decisionNote, String sourceSnapshot, UUID latestDecisionId,
            UUID exportJobId, Instant createdAt) {}

    record ExportJob(
            UUID jobId, Map<String, String> filterSnapshot, int candidateCount,
            int exportedCount, int failedCount, String status,
            ObjectReference packageReference, ObjectReference manifestReference,
            List<UUID> failedCandidateIds, Instant createdAt, Instant expiresAt,
            List<UUID> candidateIds, String packageBucket, String packageKey,
            List<ExternalReceipt> externalReceipts) {}

    record DownloadTicket(UUID ticketId, UUID jobId, Instant expiresAt, String downloadUrl) {}

    record ExternalReceipt(
            UUID receiptId, UUID jobId, String receiverName, String externalReference,
            String receiptNote, UUID recordedBy, Instant recordedAt) {}
}
