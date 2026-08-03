// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 2；源哈希: b30eca1ebbb6b533902ed4ba897e07c0daebd02a7ecf931154f9d2fb3ae0fc8e
package local.tooldefect.contracts.v2;

import java.util.List;
import java.util.Map;

public final class ContractModelsV2 {
    private ContractModelsV2() {}

    public record ObjectReference(String bucket, String objectKey, String sha256, long sizeBytes, String mediaType, String objectVersion) {}
    public record BatchAggregateCounts(long total, long completed, long defectSuspected, long normal, long inconclusive, long qualityRejected, long technicalFailed) {}
    public record ImageQualityCheck(ContractEnumsV2.ImageQualityCheckType checkType, ContractEnumsV2.ImageQualityCheckStatus status, String ruleId, String reasonCode, String userHint, Double measurement, Double threshold) {}
    public record ImageQualityResult(ContractEnumsV2.ImageQualityOverall overall, String checkerVersion, List<ImageQualityCheck> checks) {}
    public record DetectionBatch(String batchId, String batchNo, ContractEnumsV2.BatchSource source, String createdBy, ContractEnumsV2.UsageStage usageStage, String usageStageNote, ContractEnumsV2.BatchStatus status, BatchAggregateCounts counts, String createdAt, String updatedAt, long version) {}
    public record DetectionBatchItem(String batchItemId, String batchId, String captureId, ObjectReference image, ContractEnumsV2.BatchItemStatus status, ImageQualityResult quality, ContractEnumsV2.AlgorithmOutcome algorithmOutcome, ContractEnumsV2.QuickReviewDecision quickReviewDecision, String createdAt, String updatedAt) {}
    public record QuickReviewRecord(String reviewRecordId, String batchItemId, ContractEnumsV2.QuickReviewDecision decision, String submittedBy, String submittedAt, String idempotencyKey, String supersedesRecordId, String dispositionReference) {}
    public record AdminFeedbackRecord(String feedbackId, String batchItemId, ContractEnumsV2.AdminFeedbackLabel label, String note, ObjectReference annotationReference, String sourceReviewRecordId, String submittedBy, String submittedAt) {}
    public record SampleCandidate(String sampleCandidateId, String batchItemId, String feedbackId, ContractEnumsV2.SampleCandidateStatus status, String decisionNote, String exportJobId, String createdAt) {}
    public record SampleExportJob(String sampleExportJobId, Map<String, String> filterSnapshot, long candidateCount, ContractEnumsV2.ExportJobStatus status, ObjectReference packageReference, List<String> failedCandidateIds, String createdAt, String expiresAt) {}
    public record ModelUploadSession(String modelUploadId, ObjectReference quarantineObject, String declaredSha256, String modelVersion, String description, ContractEnumsV2.ModelUploadStatus status, String createdAt, String expiresAt) {}
    public record ModelValidationResult(String modelUploadId, ContractEnumsV2.ModelValidationStatus status, String packageCheck, String securityScan, String loadTest, String warmupTest, String fixedSampleTest, ObjectReference evidence, String externalSourceNote, String safeError) {}
    public record LegacyProvenanceSnapshot(String sourceType, String legacyId, String immutableSummary, String archiveReference, String sha256, String retainedUntil) {}
    public record StandardError(String errorCode, String message, String requestId, boolean retryable, Map<String, String> details) {}
}
