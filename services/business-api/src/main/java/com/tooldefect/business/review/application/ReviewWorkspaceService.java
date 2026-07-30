package com.tooldefect.business.review.application;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.detection.application.DetectionQueryService;
import com.tooldefect.business.review.domain.ReviewStatus;

@Service
public class ReviewWorkspaceService {
    private final ReviewRepository reviews;
    private final DetectionQueryService detections;

    public ReviewWorkspaceService(
            ReviewRepository reviews,
            DetectionQueryService detections) {
        this.reviews = Objects.requireNonNull(reviews);
        this.detections = Objects.requireNonNull(detections);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> get(
            UUID reviewTaskId,
            ReviewRequestContext context) {
        ReviewTaskState task = reviews.requireAuthorized(
            context.actorId(),
            reviewTaskId,
            "review:read",
            false
        );
        Map<String, Object> workspace = new LinkedHashMap<>();
        workspace.put("task", task.contractView());
        workspace.put(
            "evidence",
            evidence(
                task,
                detections.reviewEvidence(context.actorId(), task.captureId())
            )
        );
        return Collections.unmodifiableMap(workspace);
    }

    private static Map<String, Object> evidence(
            ReviewTaskState task,
            Map<String, Object> source) {
        boolean independentSecondReview =
            task.status() == ReviewStatus.SECOND_REVIEW_PENDING
            || (
                task.status() == ReviewStatus.CLAIMED
                && task.claimedFromStatus()
                    == ReviewStatus.SECOND_REVIEW_PENDING
            );
        if (!independentSecondReview) {
            return source;
        }
        Object value = source.get("images");
        if (!(value instanceof List<?> images)) {
            return source;
        }
        List<?> blinded = images.stream()
            .filter(image -> !isReviewMask(image))
            .toList();
        Map<String, Object> result = new LinkedHashMap<>(source);
        result.put("images", blinded);
        return Collections.unmodifiableMap(result);
    }

    private static boolean isReviewMask(Object value) {
        return value instanceof Map<?, ?> image
            && "REVIEW_MASK".equals(image.get("kind"));
    }
}
