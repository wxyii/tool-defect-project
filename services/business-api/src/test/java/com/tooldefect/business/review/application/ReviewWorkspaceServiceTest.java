package com.tooldefect.business.review.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.junit.jupiter.api.Test;

import com.tooldefect.business.detection.application.DetectionQueryService;
import com.tooldefect.business.detection.application.DetectionQueryRepository;
import com.tooldefect.business.review.domain.ReviewStatus;

final class ReviewWorkspaceServiceTest {
    private static final UUID TASK_ID =
        UUID.fromString("019f0000-0000-7000-8000-000000000201");
    private static final UUID CAPTURE_ID =
        UUID.fromString("019f0000-0000-7000-8000-000000000202");

    @Test
    void independentSecondReviewDoesNotReceivePriorHumanMask() {
        ReviewRepository repository = mock(ReviewRepository.class);
        Map<String, Object> evidence = Map.of(
            "images", List.of(
                Map.of("kind", "RAW", "image_id", "raw"),
                Map.of("kind", "REVIEW_MASK", "image_id", "first-mask")
            )
        );
        DetectionQueryService detections = detections(evidence);
        ReviewTaskState task = task(
            ReviewStatus.CLAIMED,
            ReviewStatus.SECOND_REVIEW_PENDING
        );
        when(repository.requireAuthorized(
            "reviewer-two",
            TASK_ID,
            "review:read",
            false
        )).thenReturn(task);

        Map<String, Object> result = new ReviewWorkspaceService(
            repository,
            detections
        ).get(
            TASK_ID,
            new ReviewRequestContext(
                "reviewer-two",
                "request",
                "00000000000000000000000000000001"
            )
        );

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> images = (List<Map<String, Object>>)
            ((Map<String, Object>) result.get("evidence")).get("images");
        assertThat(images)
            .extracting(image -> image.get("kind"))
            .containsExactly("RAW");
    }

    @Test
    void qualityAdjudicationCanReceiveAllEvidence() {
        ReviewRepository repository = mock(ReviewRepository.class);
        ReviewTaskState task = task(
            ReviewStatus.CLAIMED,
            ReviewStatus.ESCALATED
        );
        Map<String, Object> evidence = Map.of(
            "images", List.of(Map.of("kind", "REVIEW_MASK"))
        );
        DetectionQueryService detections = detections(evidence);
        when(repository.requireAuthorized(
            "quality-owner",
            TASK_ID,
            "review:read",
            false
        )).thenReturn(task);

        Map<String, Object> result = new ReviewWorkspaceService(
            repository,
            detections
        ).get(
            TASK_ID,
            new ReviewRequestContext(
                "quality-owner",
                "request",
                "00000000000000000000000000000002"
            )
        );

        assertThat(result.get("evidence")).isSameAs(evidence);
    }

    private static ReviewTaskState task(
            ReviewStatus status,
            ReviewStatus claimedFrom) {
        return new ReviewTaskState(
            TASK_ID,
            CAPTURE_ID,
            10,
            status,
            "actor",
            Instant.parse("2026-07-30T08:10:00Z"),
            claimedFrom,
            true,
            4,
            null,
            null,
            Instant.parse("2026-07-30T08:00:00Z")
        );
    }

    private static DetectionQueryService detections(
            Map<String, Object> evidence) {
        return new DetectionQueryService(new DetectionQueryRepository() {
            @Override
            public Map<String, Object> list(
                    String actorId,
                    String cursor,
                    int pageSize,
                    String businessDisposition,
                    String algorithmOutcome,
                    String modelVersion) {
                throw new UnsupportedOperationException();
            }

            @Override
            public Map<String, Object> detail(
                    String actorId,
                    UUID detectionTaskId) {
                throw new UnsupportedOperationException();
            }

            @Override
            public Map<String, Object> detailByCapture(
                    String actorId,
                    UUID captureId,
                    String permission) {
                return evidence;
            }
        });
    }
}
