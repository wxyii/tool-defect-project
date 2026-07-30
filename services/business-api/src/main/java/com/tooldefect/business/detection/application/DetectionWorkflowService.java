package com.tooldefect.business.detection.application;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.OptionalDouble;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.detection.domain.AlgorithmOutcome;
import com.tooldefect.business.detection.domain.DispositionDecision;
import com.tooldefect.business.detection.domain.DispositionPolicy;
import com.tooldefect.business.detection.domain.DispositionPolicyInput;
import com.tooldefect.business.detection.domain.PreprocessQuality;
import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.Uuid7Generator;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.domain.IdempotencyConflict;
import com.tooldefect.business.storage.application.DerivedObjectAcceptance;

@Service
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
public class DetectionWorkflowService {
    private final DetectionRepository detections;
    private final DerivedObjectAcceptance storage;
    private final IdempotencyService idempotency;
    private final Uuid7Generator identifiers;
    private final DispositionPolicy policy;
    private final Clock clock;
    private final int maximumAttempts;
    private final List<Duration> retryDelays;

    public DetectionWorkflowService(
            DetectionRepository detections,
            DerivedObjectAcceptance storage,
            IdempotencyService idempotency,
            Uuid7Generator identifiers,
            DispositionPolicy policy,
            Clock clock,
            @Value("${td.detection.maximum-attempts:3}") int maximumAttempts,
            @Value("${td.detection.retry-delay-1:PT30S}") Duration retryDelay1,
            @Value("${td.detection.retry-delay-2:PT2M}") Duration retryDelay2,
            @Value("${td.detection.retry-delay-3:PT10M}") Duration retryDelay3) {
        this.detections = Objects.requireNonNull(detections);
        this.storage = Objects.requireNonNull(storage);
        this.idempotency = Objects.requireNonNull(idempotency);
        this.identifiers = Objects.requireNonNull(identifiers);
        this.policy = Objects.requireNonNull(policy);
        this.clock = Objects.requireNonNull(clock);
        if (maximumAttempts < 1 || maximumAttempts > 10) {
            throw new IllegalArgumentException("最大推理尝试次数必须为 1 到 10");
        }
        this.maximumAttempts = maximumAttempts;
        this.retryDelays = List.of(
            requirePositive(retryDelay1),
            requirePositive(retryDelay2),
            requirePositive(retryDelay3)
        );
    }

    @Transactional
    public IdempotencyService.Response startAttempt(
            UUID detectionTaskId,
            String messageId,
            String workerId,
            String runtimeVersion,
            String modelSha256,
            String traceId,
            String actorId,
            String idempotencyKey,
            Object request) {
        return idempotency.execute(
            "startDetectionAttempt:" + detectionTaskId,
            actorId,
            idempotencyKey,
            request,
            () -> {
                var started = detections.startAttempt(
                    detectionTaskId,
                    identifiers.next(),
                    messageId,
                    workerId,
                    runtimeVersion,
                    modelSha256,
                    traceId,
                    clock.instant()
                );
                return new IdempotencyService.Response(
                    201,
                    Map.of(
                        "attempt_id", started.attemptId().toString(),
                        "attempt_no", started.attemptNumber(),
                        "status", "RUNNING"
                    )
                );
            }
        );
    }

    @Transactional
    public IdempotencyService.Response acceptResult(
            UUID attemptId,
            DetectionResultSubmission result,
            String actorId,
            String idempotencyKey) {
        String resultSha256 = CanonicalJson.sha256(result.raw());
        if (!resultSha256.equals(idempotencyKey)) {
            throw new IdempotencyConflict(
                "结果 Idempotency-Key 与规范请求摘要不一致"
            );
        }
        return idempotency.execute(
            "submitDetectionResult:" + attemptId,
            actorId,
            idempotencyKey,
            result.raw(),
            () -> acceptNewResult(attemptId, result, resultSha256)
        );
    }

    private IdempotencyService.Response acceptNewResult(
            UUID attemptId,
            DetectionResultSubmission result,
            String resultSha256) {
        DetectionRepository.AttemptContext context =
            detections.lockAttempt(attemptId);
        if (context.callbackSha256() != null) {
            if (context.callbackSha256().equals(resultSha256)
                    && resultSha256.equals(context.acceptedResultSha256())) {
                return acceptedResult(resultSha256);
            }
            throw new IdempotencyConflict(
                "同一执行尝试已经绑定不同回调摘要"
            );
        }
        requireRunning(context);
        if (!attemptId.equals(result.attemptId())
                || !context.detectionTaskId().equals(result.detectionTaskId())
                || !context.captureId().equals(result.captureId())) {
            throw new DomainViolation("结果标识与锁定任务不一致");
        }
        if (!context.expectedModelVersion().equals(result.modelVersion())
                || !context.expectedModelSha256().equals(result.modelSha256())) {
            throw new DomainViolation("结果模型版本或哈希与锁定流水线不一致");
        }
        if (Math.abs(
                result.qualifiedProbability()
                    + result.unqualifiedProbability()
                    - 1.0
            ) > 0.000001) {
            throw new DomainViolation("分类概率和必须为 1");
        }

        for (DetectionResultSubmission.DerivedArtifact artifact
                : result.artifacts()) {
            storage.confirmDerived(
                new DerivedObjectAcceptance.DerivedObject(
                    artifact.imageId(),
                    result.captureId(),
                    result.detectionTaskId(),
                    artifact.kind(),
                    artifact.bucket(),
                    artifact.objectKey(),
                    artifact.objectVersion(),
                    artifact.sha256(),
                    artifact.sizeBytes(),
                    artifact.mediaType(),
                    Map.of("accepted_attempt_id", attemptId.toString())
                )
            );
        }
        DispositionDecision decision = policy.decide(policyInput(context, result));
        UUID reviewTaskId = decision.requiresReview()
            ? identifiers.next()
            : null;
        List<UUID> regionIds = new ArrayList<>();
        for (int index = 0; index < result.regions().size(); index++) {
            regionIds.add(identifiers.next());
        }
        detections.acceptResult(
            context,
            identifiers.next(),
            result,
            resultSha256,
            decision,
            identifiers.next(),
            reviewTaskId,
            regionIds,
            clock.instant()
        );
        return acceptedResult(resultSha256);
    }

    @Transactional
    public IdempotencyService.Response acceptFailure(
            UUID attemptId,
            DetectionFailureSubmission failure,
            String actorId,
            String idempotencyKey) {
        String failureSha256 = CanonicalJson.sha256(failure.raw());
        if (!failureSha256.equals(idempotencyKey)) {
            throw new IdempotencyConflict(
                "失败 Idempotency-Key 与规范请求摘要不一致"
            );
        }
        return idempotency.execute(
            "submitDetectionFailure:" + attemptId,
            actorId,
            idempotencyKey,
            failure.raw(),
            () -> acceptNewFailure(attemptId, failure, failureSha256)
        );
    }

    private IdempotencyService.Response acceptNewFailure(
            UUID attemptId,
            DetectionFailureSubmission failure,
            String failureSha256) {
        DetectionRepository.AttemptContext context =
            detections.lockAttempt(attemptId);
        if (context.callbackSha256() != null) {
            if (context.callbackSha256().equals(failureSha256)
                    && "FAILED".equals(context.attemptStatus())) {
                return failureAccepted();
            }
            throw new IdempotencyConflict(
                "同一执行尝试已经绑定不同回调摘要"
            );
        }
        requireRunning(context);
        boolean willRetry =
            failure.retryable() && context.attemptNumber() < maximumAttempts;
        Instant retryAt = willRetry
            ? clock.instant().plus(
                retryDelays.get(
                    Math.min(
                        context.attemptNumber() - 1,
                        retryDelays.size() - 1
                    )
                )
            )
            : clock.instant();
        DispositionDecision decision = willRetry
            ? null
            : policy.technicalFailure(failure.errorCode());
        detections.acceptFailure(
            context,
            failure,
            failureSha256,
            maximumAttempts,
            retryAt,
            decision,
            willRetry ? null : identifiers.next(),
            willRetry ? null : identifiers.next(),
            clock.instant()
        );
        return failureAccepted();
    }

    private DispositionPolicyInput policyInput(
            DetectionRepository.AttemptContext context,
            DetectionResultSubmission result) {
        double maximumScore = -1;
        for (var region : result.regions()) {
            for (Object value : region.scores().values()) {
                if (value instanceof Number number) {
                    maximumScore = Math.max(maximumScore, number.doubleValue());
                }
            }
        }
        return new DispositionPolicyInput(
            false,
            captureQuality(context.captureQuality()),
            PreprocessQuality.valueOf(result.preprocessQuality()),
            AlgorithmOutcome.valueOf(result.algorithmOutcome()),
            result.confidence(),
            result.regions().size(),
            maximumScore < 0
                ? OptionalDouble.empty()
                : OptionalDouble.of(maximumScore),
            result.artifacts().stream()
                .anyMatch(value -> "DEFECT_MASK".equals(value.kind())),
            result.warnings().contains("ALGORITHM_CONFLICT"),
            context.forcedReview(),
            context.sampledReview()
        );
    }

    private static PreprocessQuality captureQuality(String value) {
        return switch (value) {
            case "OK" -> PreprocessQuality.OK;
            case "QUALITY_WARNING" -> PreprocessQuality.WARNING;
            case "QUALITY_REJECTED" -> PreprocessQuality.REJECTED;
            default -> throw new DomainViolation("采集质量状态不合法");
        };
    }

    private static void requireRunning(
            DetectionRepository.AttemptContext context) {
        if (!"RUNNING".equals(context.attemptStatus())) {
            throw new DomainViolation("只有 RUNNING 尝试可以接受回调");
        }
    }

    private static IdempotencyService.Response acceptedResult(String digest) {
        return new IdempotencyService.Response(
            200,
            Map.of("accepted", true, "result_sha256", digest)
        );
    }

    private IdempotencyService.Response failureAccepted() {
        return new IdempotencyService.Response(
            200,
            Map.of(
                "accepted", true,
                "request_id", identifiers.next().toString()
            )
        );
    }

    private static Duration requirePositive(Duration value) {
        if (value == null || value.isNegative() || value.isZero()) {
            throw new IllegalArgumentException("推理重试间隔必须大于 0");
        }
        return value;
    }
}
