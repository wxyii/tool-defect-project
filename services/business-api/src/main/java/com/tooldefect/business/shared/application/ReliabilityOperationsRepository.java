package com.tooldefect.business.shared.application;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

public interface ReliabilityOperationsRepository {
    enum IssueType {
        OUTBOX_DEAD,
        QUEUE_DEAD_LETTER,
        AVAILABLE_OBJECT_MISSING,
        OBJECT_INTEGRITY_MISMATCH,
        STAGING_OBJECT_ORPHANED,
        DATABASE_UNWRITABLE,
        MODEL_NOT_READY,
        MONITORING_BLIND
    }

    enum Severity {
        CRITICAL,
        HIGH,
        MEDIUM,
        LOW
    }

    enum ActionType {
        ACKNOWLEDGE,
        RETRY_ORIGINAL,
        CREATE_NEW_TASK,
        REATTACH_OBJECT,
        QUARANTINE_OBJECT,
        CLOSE
    }

    record IssueCandidate(
        IssueType issueType,
        Severity severity,
        String resourceType,
        String resourceId,
        UUID captureId,
        Map<String, Object> observedState
    ) {
    }

    record Issue(
        UUID issueId,
        String fingerprint,
        IssueType issueType,
        Severity severity,
        String resourceType,
        String resourceId,
        UUID captureId,
        Map<String, Object> observedState,
        Instant detectedAt,
        String requestId,
        String traceId
    ) {
    }

    record Action(
        UUID actionId,
        UUID auditId,
        UUID issueId,
        ActionType actionType,
        String replacementResourceId,
        String actorId,
        Set<String> actorPermissions,
        String reason,
        String requestId,
        String traceId,
        Instant occurredAt
    ) {
    }

    List<IssueCandidate> discoverDatabaseIssues(
        Instant stagingBefore,
        int limit
    );

    boolean appendIssue(Issue issue);

    Optional<Issue> findIssue(UUID issueId);

    void applyAction(Issue issue, Action action);
}
