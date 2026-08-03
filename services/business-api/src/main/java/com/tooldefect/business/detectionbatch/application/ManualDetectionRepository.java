package com.tooldefect.business.detectionbatch.application;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface ManualDetectionRepository {
    BatchView createBatch(UUID ownerId, String usageStage, String usageStageNote);
    UploadIntent addItem(UUID batchId, UUID itemId, UUID ownerId, String fileName, long sizeBytes,
                         String mediaType, String sha256, String bucket, String objectKey,
                         Instant expiresAt, int maximumItems);
    Optional<UploadIntent> findUpload(UUID batchId, UUID itemId, UUID ownerId);
    ItemView confirmUpload(UUID batchId, UUID itemId, UUID ownerId, String objectVersion,
                           int width, int height);
    void recordUploadFailure(UUID batchId, UUID itemId, UUID ownerId, String errorCode);
    void deleteItem(UUID batchId, UUID itemId, UUID ownerId, long expectedVersion);
    BatchView submit(UUID batchId, UUID ownerId, long expectedVersion, String idempotencyKey);
    List<TaskDispatch> queuedTasks(UUID batchId, String submitIdempotencyKey);
    Optional<BatchView> findBatch(UUID batchId, UUID actorId, boolean canReadAll);
    Optional<ItemView> findItem(UUID batchId, UUID itemId, UUID actorId, boolean canReadAll);
    Page list(UUID actorId, boolean canReadAll, Instant beforeCreatedAt, UUID beforeId, int limit);
    List<OrphanObject> claimExpiredOrphans(Instant cutoff, int limit);
    void recordOrphanCleanup(OrphanObject orphan, boolean resolved, String errorCode);

    record Counts(int total, int completed, int defectSuspected, int normal,
                  int inconclusive, int qualityRejected, int technicalFailed) {}
    record BatchView(UUID batchId, String batchNo, UUID createdBy, String usageStage,
                     String usageStageNote, String status, Counts counts, Instant createdAt,
                     Instant updatedAt, long version) {}
    record ItemView(UUID itemId, UUID batchId, String bucket, String objectKey,
                    String objectVersion, String sha256, long sizeBytes, String mediaType,
                    String status, String algorithmOutcome, String quickReviewDecision,
                    Instant createdAt, Instant updatedAt) {}
    record UploadIntent(UUID uploadId, ItemView item, UUID ownerId, String fileName,
                        long expectedSizeBytes, String expectedMediaType,
                        String expectedSha256, Instant expiresAt) {}
    record Page(List<BatchView> items, String nextCursor) {}
    record OrphanObject(UUID batchId, UUID itemId, String bucket, String objectKey) {}
    record TaskDispatch(UUID detectionTaskId, UUID batchItemId, String bucket,
                        String objectKey, String objectVersion, String sha256,
                        long sizeBytes, String mediaType) {}
}
