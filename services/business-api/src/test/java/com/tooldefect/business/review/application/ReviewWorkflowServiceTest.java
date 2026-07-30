package com.tooldefect.business.review.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.review.domain.ReviewAccessDenied;
import com.tooldefect.business.review.domain.ReviewConflict;
import com.tooldefect.business.review.domain.ReviewStatus;
import com.tooldefect.business.shared.application.IdempotencyRepository;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.Uuid7Generator;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.storage.application.ReviewAnnotationStorage;

class ReviewWorkflowServiceTest {
    private static final Instant NOW = Instant.parse("2026-07-30T06:00:00Z");
    private static final UUID TASK_ID = UUID.fromString(
        "019fb1b0-0000-7000-8000-000000000001"
    );
    private static final UUID CAPTURE_ID = UUID.fromString(
        "019fb1b0-0000-7000-8000-000000000002"
    );
    private static final ReviewRequestContext REVIEWER_A =
        new ReviewRequestContext(
            "reviewer-a",
            "request-a",
            "a".repeat(32)
        );
    private static final ReviewRequestContext REVIEWER_B =
        new ReviewRequestContext(
            "reviewer-b",
            "request-b",
            "b".repeat(32)
        );

    private ReviewRepository repository;
    private AuditTrail audit;
    private ReviewWorkflowService service;

    @BeforeEach
    void setUp() {
        repository = mock(ReviewRepository.class);
        audit = mock(AuditTrail.class);
        ReviewAnnotationStorage annotations =
            mock(ReviewAnnotationStorage.class);
        IdempotencyRepository idempotencyRepository =
            mock(IdempotencyRepository.class);
        when(idempotencyRepository.find(anyString(), anyString(), anyString()))
            .thenReturn(Optional.empty());
        Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
        service = new ReviewWorkflowService(
            repository,
            annotations,
            new IdempotencyService(idempotencyRepository),
            audit,
            new Uuid7Generator(clock, new SecureRandom(new byte[] {4, 1})),
            clock,
            Duration.ofMinutes(5)
        );
    }

    @Test
    void concurrentClaimsAllowOnlyTheFirstVersion() {
        ReviewTaskState pending = task(
            ReviewStatus.PENDING,
            null,
            null,
            null,
            false,
            0
        );
        ReviewTaskState claimed = task(
            ReviewStatus.CLAIMED,
            "reviewer-a",
            NOW.plusSeconds(300),
            ReviewStatus.PENDING,
            false,
            1
        );
        when(repository.requireAuthorized(
                "reviewer-a", TASK_ID, "review:claim", true))
            .thenReturn(pending);
        when(repository.requireAuthorized(
                "reviewer-a", TASK_ID, "review:claim", false))
            .thenReturn(claimed);
        when(repository.claim(
                eq(TASK_ID),
                eq("reviewer-a"),
                eq(0L),
                any(Instant.class),
                eq("PENDING")))
            .thenReturn(true, false);

        var first = service.claim(
            TASK_ID,
            0,
            "claim-key-first",
            actionRequest(),
            REVIEWER_A
        );

        assertThat(first.body()).containsEntry("record_version", 1L);
        assertThatThrownBy(() -> service.claim(
            TASK_ID,
            0,
            "claim-key-second",
            actionRequest(),
            REVIEWER_A
        )).isInstanceOf(ReviewConflict.class);
        verify(repository, times(2)).claim(
            eq(TASK_ID),
            eq("reviewer-a"),
            eq(0L),
            any(Instant.class),
            eq("PENDING")
        );
    }

    @Test
    void listingRequeuesExpiredLeasesBeforeReturningThePool() {
        when(repository.list(
                "reviewer-a", null, 50, "PENDING"))
            .thenReturn(Map.of(
                "items", List.of(),
                "next_cursor", "",
                "has_more", false
            ));

        service.list(REVIEWER_A, null, 50, "PENDING");

        verify(repository).requeueExpired(NOW);
        verify(repository).list("reviewer-a", null, 50, "PENDING");
    }

    @Test
    void firstReviewerCannotClaimTheBlindSecondReview() {
        ReviewTaskState secondPending = task(
            ReviewStatus.SECOND_REVIEW_PENDING,
            null,
            null,
            null,
            true,
            1
        );
        when(repository.requireAuthorized(
                "reviewer-a", TASK_ID, "review:claim", true))
            .thenReturn(secondPending);
        when(repository.records(TASK_ID)).thenReturn(List.of(
            record("reviewer-a", "FAIL", 1)
        ));

        assertThatThrownBy(() -> service.claim(
            TASK_ID,
            1,
            "second-claim-key",
            actionRequest(),
            REVIEWER_A
        )).isInstanceOf(ReviewAccessDenied.class);
        verify(repository, never()).claim(
            any(), anyString(), anyLong(), any(), anyString()
        );
    }

    @Test
    void inconsistentBlindReviewsEscalateWithoutChangingDisposition() {
        ReviewTaskState claimed = task(
            ReviewStatus.CLAIMED,
            "reviewer-b",
            NOW.plusSeconds(300),
            ReviewStatus.SECOND_REVIEW_PENDING,
            true,
            1
        );
        ReviewTaskState escalated = task(
            ReviewStatus.ESCALATED,
            null,
            null,
            null,
            true,
            2
        );
        when(repository.requireAuthorized(
                "reviewer-b", TASK_ID, "review:submit", true))
            .thenReturn(claimed);
        when(repository.requireAuthorized(
                "reviewer-b", TASK_ID, "review:submit", false))
            .thenReturn(escalated);
        when(repository.records(TASK_ID)).thenReturn(List.of(
            record("reviewer-a", "FAIL", 1)
        ));
        when(repository.completeClaim(
                TASK_ID, "reviewer-b", 1, "ESCALATED"))
            .thenReturn(true);

        var response = service.submit(
            TASK_ID,
            1,
            "submit-reviewer-b",
            submissionRequest("PASS"),
            submission("PASS"),
            REVIEWER_B
        );

        assertThat(response.body())
            .containsEntry("task_status", "ESCALATED")
            .containsEntry("business_disposition", "HOLD");
        verify(repository, never()).appendDisposition(
            any(), any(), any(), anyString(), anyString(), anyString(), any()
        );
    }

    @Test
    void singleReviewCreatesFinalDispositionAndImmutableRecord() {
        ReviewTaskState claimed = task(
            ReviewStatus.CLAIMED,
            "reviewer-a",
            NOW.plusSeconds(300),
            ReviewStatus.PENDING,
            false,
            1
        );
        ReviewTaskState resolved = task(
            ReviewStatus.RESOLVED,
            null,
            null,
            null,
            false,
            2
        );
        when(repository.requireAuthorized(
                "reviewer-a", TASK_ID, "review:submit", true))
            .thenReturn(claimed);
        when(repository.requireAuthorized(
                "reviewer-a", TASK_ID, "review:submit", false))
            .thenReturn(resolved);
        when(repository.records(TASK_ID)).thenReturn(List.of());
        when(repository.completeClaim(
                TASK_ID, "reviewer-a", 1, "RESOLVED"))
            .thenReturn(true);

        var response = service.submit(
            TASK_ID,
            1,
            "submit-reviewer-a",
            submissionRequest("FAIL"),
            submission("FAIL"),
            REVIEWER_A
        );

        assertThat(response.status()).isEqualTo(201);
        assertThat(response.body())
            .containsEntry("task_status", "RESOLVED")
            .containsEntry("business_disposition", "FAIL")
            .containsEntry("record_version", 2L);
        verify(repository).insertRecord(
            any(),
            eq(claimed),
            eq("reviewer-a"),
            any(ReviewSubmission.class),
            eq(1),
            isNull(),
            isNull(),
            eq(false),
            matches("[0-9a-f]{64}"),
            eq(NOW)
        );
        verify(repository).appendDisposition(
            any(),
            eq(claimed),
            any(),
            eq("reviewer-a"),
            eq("FAIL"),
            eq("MODEL_FALSE_NEGATIVE"),
            eq(NOW)
        );
    }

    @Test
    void expiredClaimCannotSubmit() {
        ReviewTaskState expired = task(
            ReviewStatus.CLAIMED,
            "reviewer-a",
            NOW,
            ReviewStatus.PENDING,
            false,
            1
        );
        when(repository.requireAuthorized(
                "reviewer-a", TASK_ID, "review:submit", true))
            .thenReturn(expired);

        assertThatThrownBy(() -> service.submit(
            TASK_ID,
            1,
            "expired-submit",
            submissionRequest("HOLD"),
            submission("HOLD"),
            REVIEWER_A
        )).isInstanceOf(ReviewConflict.class);
        verify(repository, never()).insertRecord(
            any(), any(), anyString(), any(), anyInt(), any(), any(),
            anyBoolean(), anyString(), any()
        );
    }

    @Test
    void qualityManagerAdjudicatesEscalatedConflict() {
        ReviewTaskState claimed = task(
            ReviewStatus.CLAIMED,
            "reviewer-a",
            NOW.plusSeconds(300),
            ReviewStatus.ESCALATED,
            true,
            4
        );
        ReviewTaskState resolved = task(
            ReviewStatus.RESOLVED,
            null,
            null,
            null,
            true,
            5
        );
        when(repository.requireAuthorized(
                "reviewer-a", TASK_ID, "review:submit", true))
            .thenReturn(claimed);
        when(repository.requireAuthorized(
                "reviewer-a", TASK_ID, "review:submit", false))
            .thenReturn(resolved);
        when(repository.records(TASK_ID)).thenReturn(List.of(
            record("reviewer-a", "PASS", 1),
            record("reviewer-b", "FAIL", 2)
        ));
        when(repository.hasPermission("reviewer-a", "quality:override"))
            .thenReturn(true);
        when(repository.completeClaim(
                TASK_ID, "reviewer-a", 4, "RESOLVED"))
            .thenReturn(true);

        var response = service.submit(
            TASK_ID,
            4,
            "quality-adjudication",
            submissionRequest("FAIL"),
            submission("FAIL"),
            REVIEWER_A
        );

        assertThat(response.body())
            .containsEntry("task_status", "RESOLVED")
            .containsEntry("business_disposition", "FAIL");
        verify(repository).insertRecord(
            any(), eq(claimed), eq("reviewer-a"), any(), eq(3), any(),
            isNull(), eq(true), matches("[0-9a-f]{64}"), eq(NOW)
        );
    }

    @Test
    void correctionRevisionCreatesNewTaskWithoutMutatingClosedRecord() {
        ReviewTaskState resolved = task(
            ReviewStatus.RESOLVED,
            null,
            null,
            null,
            false,
            8
        );
        var closedRecord = record("reviewer-a", "PASS", 1);
        when(repository.requireAuthorized(
                "reviewer-a", TASK_ID, "quality:override", true))
            .thenReturn(resolved);
        when(repository.records(TASK_ID)).thenReturn(List.of(closedRecord));
        when(repository.openRevision(
                any(), eq(resolved), eq(closedRecord.reviewRecordId()),
                eq(0), eq(NOW)))
            .thenAnswer(invocation -> invocation.getArgument(0));

        UUID revisionId = service.openRevision(
            TASK_ID,
            "P0",
            "发现原判定证据错误",
            REVIEWER_A
        );

        assertThat(revisionId).isNotEqualTo(TASK_ID);
        verify(repository).openRevision(
            revisionId,
            resolved,
            closedRecord.reviewRecordId(),
            0,
            NOW
        );
        verify(repository, never()).insertRecord(
            any(), any(), anyString(), any(), anyInt(), any(), any(),
            anyBoolean(), anyString(), any()
        );
        verify(audit).append(any());
    }

    @Test
    void trainingEligibilityRequiresSeparateDatasetApproval() {
        UUID reviewRecordId = UUID.randomUUID();
        when(repository.hasPermission("reviewer-a", "dataset:approve"))
            .thenReturn(false, true);

        assertThatThrownBy(() -> service.decideTrainingEligibility(
            reviewRecordId,
            true,
            "批准训练候选",
            REVIEWER_A
        )).isInstanceOf(ReviewAccessDenied.class);

        service.decideTrainingEligibility(
            reviewRecordId,
            true,
            "批准训练候选",
            REVIEWER_A
        );

        verify(repository).appendTrainingDecision(
            any(),
            eq(reviewRecordId),
            eq("reviewer-a"),
            eq("APPROVED"),
            eq("批准训练候选"),
            eq(NOW)
        );
        verify(audit).append(any());
    }

    @Test
    void invalidPriorityIsRejectedBeforeRepositoryMutation() {
        assertThatThrownBy(() -> service.reprioritize(
            TASK_ID,
            0,
            "P4",
            "非法降低优先级",
            REVIEWER_A
        )).isInstanceOf(DomainViolation.class);
        verify(repository, never()).changePriority(any(), anyLong(), anyInt());
    }

    private static ReviewTaskState task(
            ReviewStatus status,
            String claimedBy,
            Instant lease,
            ReviewStatus claimedFrom,
            boolean second,
            long version) {
        return new ReviewTaskState(
            TASK_ID,
            CAPTURE_ID,
            10,
            status,
            claimedBy,
            lease,
            claimedFrom,
            second,
            version,
            null,
            null,
            NOW.minusSeconds(60)
        );
    }

    private static ReviewRepository.ReviewRecordState record(
            String reviewer,
            String decision,
            int round) {
        return new ReviewRepository.ReviewRecordState(
            UUID.randomUUID(),
            reviewer,
            decision,
            "CONFIRMED_CORRECT",
            round,
            UUID.randomUUID(),
            null,
            false,
            NOW.minusSeconds(30)
        );
    }

    private static Map<String, Object> actionRequest() {
        return Map.of(
            "client_request_id",
            "019fb1b0-0000-7000-8000-000000000010",
            "reason",
            "开始复核"
        );
    }

    private static Map<String, Object> submissionRequest(String decision) {
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("decision", decision);
        request.put("reason_code", "MODEL_FALSE_NEGATIVE");
        request.put("comment", "人工确认");
        request.put("defect_type_codes", List.of("SPALLING"));
        request.put("annotation_image_id", null);
        request.put("client_submitted_at", NOW.toString());
        return request;
    }

    private static ReviewSubmission submission(String decision) {
        return new ReviewSubmission(
            decision,
            "MODEL_FALSE_NEGATIVE",
            "人工确认",
            List.of("SPALLING"),
            null,
            NOW
        );
    }

}
