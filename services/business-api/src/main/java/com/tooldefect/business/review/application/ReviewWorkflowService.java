package com.tooldefect.business.review.application;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.audit.domain.AuditRecord;
import com.tooldefect.business.review.domain.ReviewAccessDenied;
import com.tooldefect.business.review.domain.ReviewConflict;
import com.tooldefect.business.review.domain.ReviewStatus;
import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.Uuid7Generator;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.storage.application.ReviewAnnotationStorage;

@Service
public class ReviewWorkflowService {
    private static final String HOLD = "HOLD";

    private final ReviewRepository repository;
    private final ReviewAnnotationStorage annotations;
    private final IdempotencyService idempotency;
    private final AuditTrail audit;
    private final Uuid7Generator ids;
    private final Clock clock;
    private final Duration claimLease;

    public ReviewWorkflowService(
            ReviewRepository repository,
            ReviewAnnotationStorage annotations,
            IdempotencyService idempotency,
            AuditTrail audit,
            Uuid7Generator ids,
            Clock clock,
            @Value("${td.review.claim-lease:PT5M}") Duration claimLease) {
        this.repository = Objects.requireNonNull(repository);
        this.annotations = Objects.requireNonNull(annotations);
        this.idempotency = Objects.requireNonNull(idempotency);
        this.audit = Objects.requireNonNull(audit);
        this.ids = Objects.requireNonNull(ids);
        this.clock = Objects.requireNonNull(clock);
        this.claimLease = Objects.requireNonNull(claimLease);
        if (claimLease.isNegative()
                || claimLease.isZero()
                || claimLease.compareTo(Duration.ofHours(1)) > 0) {
            throw new DomainViolation("复核认领租约必须大于 0 且不超过 1 小时");
        }
    }

    @Transactional
    public Map<String, Object> list(
            ReviewRequestContext context,
            String cursor,
            int pageSize,
            String status) {
        if (pageSize < 1 || pageSize > 100) {
            throw new DomainViolation("复核任务页长必须为 1 到 100");
        }
        if (status != null) {
            try {
                ReviewStatus.valueOf(status);
            } catch (IllegalArgumentException invalid) {
                throw new DomainViolation("复核状态不合法", invalid);
            }
        }
        repository.requeueExpired(Instant.now(clock));
        return repository.list(
            context.actorId(),
            cursor,
            pageSize,
            status
        );
    }

    @Transactional
    public IdempotencyService.Response claim(
            UUID reviewTaskId,
            long expectedVersion,
            String idempotencyKey,
            Map<String, Object> request,
            ReviewRequestContext context) {
        Map<String, Object> digestInput = commandDigest(
            reviewTaskId,
            expectedVersion,
            request
        );
        return idempotency.execute(
            "claimReviewTask",
            context.actorId(),
            idempotencyKey,
            digestInput,
            () -> {
                Instant now = Instant.now(clock);
                repository.requeueExpired(now);
                ReviewTaskState task = repository.requireAuthorized(
                    context.actorId(),
                    reviewTaskId,
                    "review:claim",
                    true
                );
                ReviewStatus phase = task.status();
                if (!List.of(
                        ReviewStatus.PENDING,
                        ReviewStatus.SECOND_REVIEW_PENDING,
                        ReviewStatus.ESCALATED
                    ).contains(phase)) {
                    throw new ReviewConflict("复核任务当前状态不可认领");
                }
                if (phase == ReviewStatus.ESCALATED
                        && !repository.hasPermission(
                            context.actorId(),
                            "quality:override"
                        )) {
                    throw new ReviewAccessDenied("只有质量负责人可以认领升级任务");
                }
                if (phase == ReviewStatus.SECOND_REVIEW_PENDING
                        && repository.records(reviewTaskId).stream()
                            .anyMatch(record ->
                                record.reviewerId().equals(context.actorId()))) {
                    throw new ReviewAccessDenied("第一复核人不能执行二审");
                }
                Instant expiresAt = now.plus(claimLease);
                if (!repository.claim(
                        reviewTaskId,
                        context.actorId(),
                        expectedVersion,
                        expiresAt,
                        phase.name())) {
                    throw new ReviewConflict("复核任务版本或认领状态已变化");
                }
                ReviewTaskState updated = repository.requireAuthorized(
                    context.actorId(),
                    reviewTaskId,
                    "review:claim",
                    false
                );
                appendAudit(
                    context,
                    "review.claim",
                    task,
                    updated,
                    text(request.get("reason")),
                    now
                );
                return new IdempotencyService.Response(
                    200,
                    updated.contractView()
                );
            }
        );
    }

    @Transactional
    public IdempotencyService.Response release(
            UUID reviewTaskId,
            long expectedVersion,
            String idempotencyKey,
            Map<String, Object> request,
            ReviewRequestContext context) {
        return idempotency.execute(
            "releaseReviewTask",
            context.actorId(),
            idempotencyKey,
            commandDigest(reviewTaskId, expectedVersion, request),
            () -> {
                Instant now = Instant.now(clock);
                ReviewTaskState task = repository.requireAuthorized(
                    context.actorId(),
                    reviewTaskId,
                    "review:claim",
                    true
                );
                requireOwnedLiveClaim(task, context.actorId(), now);
                ReviewStatus restored = task.claimedFromStatus();
                if (restored == null) {
                    restored = ReviewStatus.PENDING;
                }
                if (!repository.release(
                        reviewTaskId,
                        context.actorId(),
                        expectedVersion,
                        restored.name())) {
                    throw new ReviewConflict("复核任务版本或租约已变化");
                }
                ReviewTaskState updated = repository.requireAuthorized(
                    context.actorId(),
                    reviewTaskId,
                    "review:claim",
                    false
                );
                appendAudit(
                    context,
                    "review.release",
                    task,
                    updated,
                    text(request.get("reason")),
                    now
                );
                return new IdempotencyService.Response(
                    200,
                    updated.contractView()
                );
            }
        );
    }

    @Transactional
    public IdempotencyService.Response submit(
            UUID reviewTaskId,
            long expectedVersion,
            String idempotencyKey,
            Map<String, Object> request,
            ReviewSubmission submission,
            ReviewRequestContext context) {
        if (submission.clientSubmittedAt().isAfter(
                Instant.now(clock).plus(Duration.ofMinutes(5)))) {
            throw new DomainViolation("客户端提交时间不能显著晚于服务端");
        }
        return idempotency.execute(
            "submitReview",
            context.actorId(),
            idempotencyKey,
            commandDigest(reviewTaskId, expectedVersion, request),
            () -> submitOnce(
                reviewTaskId,
                expectedVersion,
                request,
                submission,
                context
            )
        );
    }

    @Transactional
    public IdempotencyService.Response issueAnnotationUpload(
            UUID reviewTaskId,
            String idempotencyKey,
            Map<String, Object> request,
            long sizeBytes,
            String sha256,
            int width,
            int height,
            ReviewRequestContext context) {
        return idempotency.execute(
            "createAnnotationUploadTicket",
            context.actorId(),
            idempotencyKey,
            Map.of(
                "review_task_id", reviewTaskId.toString(),
                "request", request
            ),
            () -> {
                ReviewTaskState task = repository.requireAuthorized(
                    context.actorId(),
                    reviewTaskId,
                    "review:annotate",
                    true
                );
                requireOwnedLiveClaim(
                    task,
                    context.actorId(),
                    Instant.now(clock)
                );
                UUID imageId = ids.next();
                var ticket = annotations.issue(
                    imageId,
                    reviewTaskId,
                    task.captureId(),
                    sizeBytes,
                    sha256,
                    width,
                    height
                );
                Map<String, Object> upload = new LinkedHashMap<>();
                upload.put("method", ticket.method());
                upload.put("url", ticket.url().toString());
                upload.put("headers", ticket.headers());
                upload.put("expires_at", ticket.expiresAt().toString());
                appendAudit(
                    context,
                    "review.annotation.issue",
                    task,
                    task,
                    null,
                    Instant.now(clock)
                );
                return new IdempotencyService.Response(
                    201,
                    Map.of(
                        "image_id", imageId.toString(),
                        "upload", upload
                    )
                );
            }
        );
    }

    @Transactional
    public IdempotencyService.Response confirmAnnotation(
            UUID reviewTaskId,
            UUID imageId,
            String idempotencyKey,
            Map<String, Object> request,
            long sizeBytes,
            String sha256,
            String uploadReceipt,
            ReviewRequestContext context) {
        Map<String, Object> digestInput = new LinkedHashMap<>();
        digestInput.put("review_task_id", reviewTaskId.toString());
        digestInput.put("image_id", imageId.toString());
        digestInput.put("request", request);
        return idempotency.execute(
            "completeReviewAnnotation",
            context.actorId(),
            idempotencyKey,
            digestInput,
            () -> {
                ReviewTaskState task = repository.requireAuthorized(
                    context.actorId(),
                    reviewTaskId,
                    "review:annotate",
                    true
                );
                requireOwnedLiveClaim(
                    task,
                    context.actorId(),
                    Instant.now(clock)
                );
                var confirmed = annotations.confirm(
                    reviewTaskId,
                    imageId,
                    sizeBytes,
                    sha256,
                    uploadReceipt
                );
                appendAudit(
                    context,
                    "review.annotation.confirm",
                    task,
                    task,
                    null,
                    Instant.now(clock)
                );
                return new IdempotencyService.Response(
                    200,
                    Map.of(
                        "image_id", confirmed.imageId().toString(),
                        "state", "AVAILABLE",
                        "sha256", confirmed.sha256()
                    )
                );
            }
        );
    }

    private IdempotencyService.Response submitOnce(
            UUID reviewTaskId,
            long expectedVersion,
            Map<String, Object> request,
            ReviewSubmission submission,
            ReviewRequestContext context) {
        Instant now = Instant.now(clock);
        ReviewTaskState task = repository.requireAuthorized(
            context.actorId(),
            reviewTaskId,
            "review:submit",
            true
        );
        requireOwnedLiveClaim(task, context.actorId(), now);
        List<ReviewRepository.ReviewRecordState> history =
            repository.records(reviewTaskId);
        ReviewStatus phase = task.claimedFromStatus() == null
            ? ReviewStatus.PENDING
            : task.claimedFromStatus();

        int round;
        boolean adjudication = false;
        UUID group;
        UUID supersedes = null;
        ReviewStatus nextStatus;
        String businessDisposition = HOLD;

        if (phase == ReviewStatus.PENDING) {
            round = 1;
            group = task.requiresSecondReview() ? ids.next() : null;
            supersedes = task.supersedesReviewRecordId();
            nextStatus = task.requiresSecondReview()
                ? ReviewStatus.SECOND_REVIEW_PENDING
                : ReviewStatus.RESOLVED;
        } else if (phase == ReviewStatus.SECOND_REVIEW_PENDING) {
            ReviewRepository.ReviewRecordState first = primary(history);
            if (first.reviewerId().equals(context.actorId())) {
                throw new ReviewAccessDenied("第一复核人不能执行二审");
            }
            round = 2;
            group = first.independentReviewGroup();
            nextStatus = first.decision().equals(submission.decision())
                ? ReviewStatus.RESOLVED
                : ReviewStatus.ESCALATED;
        } else if (phase == ReviewStatus.ESCALATED) {
            if (!repository.hasPermission(
                    context.actorId(),
                    "quality:override")) {
                throw new ReviewAccessDenied("只有质量负责人可以裁决复核冲突");
            }
            round = history.stream()
                .mapToInt(ReviewRepository.ReviewRecordState::reviewRound)
                .max()
                .orElse(2) + 1;
            group = history.isEmpty()
                ? ids.next()
                : history.get(0).independentReviewGroup();
            adjudication = true;
            nextStatus = ReviewStatus.RESOLVED;
        } else {
            throw new ReviewConflict("认领来源状态不可提交");
        }

        UUID recordId = ids.next();
        repository.insertRecord(
            recordId,
            task,
            context.actorId(),
            submission,
            round,
            group,
            supersedes,
            adjudication,
            CanonicalJson.sha256(request),
            now
        );
        if (!repository.completeClaim(
                reviewTaskId,
                context.actorId(),
                expectedVersion,
                nextStatus.name())) {
            throw new ReviewConflict("复核任务版本或租约已变化");
        }
        if (nextStatus == ReviewStatus.RESOLVED) {
            businessDisposition = submission.decision();
            repository.appendDisposition(
                ids.next(),
                task,
                recordId,
                context.actorId(),
                submission.decision(),
                submission.reasonCode(),
                now
            );
        }
        ReviewTaskState updated = repository.requireAuthorized(
            context.actorId(),
            reviewTaskId,
            "review:submit",
            false
        );
        appendAudit(
            context,
            adjudication ? "review.adjudicate" : "review.submit",
            task,
            updated,
            submission.reasonCode(),
            now
        );
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("review_record_id", recordId.toString());
        response.put("task_status", nextStatus.name());
        response.put("business_disposition", businessDisposition);
        response.put("record_version", updated.recordVersion());
        return new IdempotencyService.Response(201, response);
    }

    @Transactional
    public ReviewTaskState reprioritize(
            UUID reviewTaskId,
            long expectedVersion,
            String priority,
            String reason,
            ReviewRequestContext context) {
        ReviewTaskState task = repository.requireAuthorized(
            context.actorId(),
            reviewTaskId,
            "review:escalate",
            true
        );
        int value = ReviewTaskState.priorityValue(priority);
        if (!repository.changePriority(reviewTaskId, expectedVersion, value)) {
            throw new ReviewConflict("复核任务优先级版本已变化");
        }
        ReviewTaskState updated = repository.requireAuthorized(
            context.actorId(),
            reviewTaskId,
            "review:escalate",
            false
        );
        appendAudit(
            context,
            "review.priority.change",
            task,
            updated,
            reason,
            Instant.now(clock)
        );
        return updated;
    }

    @Transactional
    public UUID openRevision(
            UUID resolvedTaskId,
            String priority,
            String reason,
            ReviewRequestContext context) {
        ReviewTaskState task = repository.requireAuthorized(
            context.actorId(),
            resolvedTaskId,
            "quality:override",
            true
        );
        if (task.status() != ReviewStatus.RESOLVED) {
            throw new ReviewConflict("只有已关闭任务可以创建纠错修订");
        }
        ReviewRepository.ReviewRecordState latest = repository.records(
            resolvedTaskId
        ).stream().reduce((left, right) -> right).orElseThrow(() ->
            new ReviewConflict("已关闭任务缺少复核记录")
        );
        UUID newTaskId = ids.next();
        repository.openRevision(
            newTaskId,
            task,
            latest.reviewRecordId(),
            ReviewTaskState.priorityValue(priority),
            Instant.now(clock)
        );
        audit.append(new AuditRecord(
            ids.next(),
            Instant.now(clock),
            "USER",
            context.actorId(),
            "review.revision.open",
            "review_task",
            newTaskId.toString(),
            CanonicalJson.sha256(task.contractView()),
            null,
            requireReason(reason),
            context.requestId(),
            context.traceId(),
            "SUCCESS",
            null
        ));
        return newTaskId;
    }

    @Transactional
    public void decideTrainingEligibility(
            UUID reviewRecordId,
            boolean approved,
            String reason,
            ReviewRequestContext context) {
        if (!repository.hasPermission(
                context.actorId(),
                "dataset:approve")) {
            throw new ReviewAccessDenied("只有质量负责人可以批准训练候选");
        }
        Instant now = Instant.now(clock);
        repository.appendTrainingDecision(
            ids.next(),
            reviewRecordId,
            context.actorId(),
            approved ? "APPROVED" : "REJECTED",
            requireReason(reason),
            now
        );
        audit.append(new AuditRecord(
            ids.next(),
            now,
            "USER",
            context.actorId(),
            approved
                ? "review.training.approve"
                : "review.training.reject",
            "review_record",
            reviewRecordId.toString(),
            null,
            null,
            reason,
            context.requestId(),
            context.traceId(),
            "SUCCESS",
            null
        ));
    }

    private static ReviewRepository.ReviewRecordState primary(
            List<ReviewRepository.ReviewRecordState> history) {
        return history.stream()
            .filter(record -> record.reviewRound() == 1)
            .findFirst()
            .orElseThrow(() ->
                new ReviewConflict("二审任务缺少首轮不可变记录")
            );
    }

    private static void requireOwnedLiveClaim(
            ReviewTaskState task,
            String actorId,
            Instant now) {
        if (task.status() != ReviewStatus.CLAIMED
                || !actorId.equals(task.claimedBy())) {
            throw new ReviewConflict("复核任务未由当前用户认领");
        }
        if (task.leaseExpiresAt() == null
                || !task.leaseExpiresAt().isAfter(now)) {
            throw new ReviewConflict("复核认领租约已过期");
        }
    }

    private static Map<String, Object> commandDigest(
            UUID reviewTaskId,
            long expectedVersion,
            Map<String, Object> request) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("review_task_id", reviewTaskId.toString());
        result.put("record_version", expectedVersion);
        result.put("request", request);
        return result;
    }

    private void appendAudit(
            ReviewRequestContext context,
            String action,
            ReviewTaskState before,
            ReviewTaskState after,
            String reason,
            Instant occurredAt) {
        audit.append(new AuditRecord(
            ids.next(),
            occurredAt,
            "USER",
            context.actorId(),
            action,
            "review_task",
            before.reviewTaskId().toString(),
            CanonicalJson.sha256(before.contractView()),
            CanonicalJson.sha256(after.contractView()),
            reason,
            context.requestId(),
            context.traceId(),
            "SUCCESS",
            null
        ));
    }

    private static String requireReason(String value) {
        if (value == null || value.isBlank() || value.length() > 2048) {
            throw new DomainViolation("操作原因不能为空且不能超过 2048 字符");
        }
        return value;
    }

    private static String text(Object value) {
        return value instanceof String text && !text.isBlank() ? text : null;
    }
}
