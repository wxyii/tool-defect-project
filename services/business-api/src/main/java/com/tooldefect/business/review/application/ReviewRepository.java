package com.tooldefect.business.review.application;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

public interface ReviewRepository {
    void requeueExpired(Instant now);

    Map<String, Object> list(
        String actorId,
        String cursor,
        int pageSize,
        String status
    );

    ReviewTaskState requireAuthorized(
        String actorId,
        UUID reviewTaskId,
        String permission,
        boolean forUpdate
    );

    boolean hasPermission(String actorId, String permission);

    boolean claim(
        UUID reviewTaskId,
        String actorId,
        long expectedVersion,
        Instant leaseExpiresAt,
        String claimedFromStatus
    );

    boolean release(
        UUID reviewTaskId,
        String actorId,
        long expectedVersion,
        String restoredStatus
    );

    boolean changePriority(
        UUID reviewTaskId,
        long expectedVersion,
        int priority
    );

    List<ReviewRecordState> records(UUID reviewTaskId);

    void insertRecord(
        UUID reviewRecordId,
        ReviewTaskState task,
        String actorId,
        ReviewSubmission submission,
        int reviewRound,
        UUID independentReviewGroup,
        UUID supersedesId,
        boolean adjudication,
        String submissionSha256,
        Instant submittedAt
    );

    boolean completeClaim(
        UUID reviewTaskId,
        String actorId,
        long expectedVersion,
        String nextStatus
    );

    void appendDisposition(
        UUID dispositionId,
        ReviewTaskState task,
        UUID reviewRecordId,
        String actorId,
        String decision,
        String reasonCode,
        Instant createdAt
    );

    UUID openRevision(
        UUID newTaskId,
        ReviewTaskState resolvedTask,
        UUID supersededReviewRecordId,
        int priority,
        Instant createdAt
    );

    void appendTrainingDecision(
        UUID decisionId,
        UUID reviewRecordId,
        String actorId,
        String decision,
        String reason,
        Instant createdAt
    );

    record ReviewRecordState(
        UUID reviewRecordId,
        String reviewerId,
        String decision,
        String reasonCode,
        int reviewRound,
        UUID independentReviewGroup,
        UUID supersedesId,
        boolean adjudication,
        Instant submittedAt
    ) {
    }
}
