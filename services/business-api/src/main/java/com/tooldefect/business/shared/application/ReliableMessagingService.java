package com.tooldefect.business.shared.application;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.ThreadLocalRandom;
import java.util.Objects;

import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.messaging.OutboxEvent;

public final class ReliableMessagingService {
    private static final int MAXIMUM_BATCH_SIZE = 1_000;

    private final OutboxRepository outbox;
    private final MessagePublisher publisher;
    private final Clock clock;
    private final String claimOwner;
    private final Duration leaseDuration;
    private final int maximumAttempts;
    private final Duration initialBackoff;
    private final Duration maximumBackoff;
    private final double jitterRatio;

    public ReliableMessagingService(
            OutboxRepository outbox,
            MessagePublisher publisher,
            Clock clock,
            String claimOwner,
            Duration leaseDuration) {
        this(
            outbox,
            publisher,
            clock,
            claimOwner,
            leaseDuration,
            10,
            Duration.ofSeconds(1),
            Duration.ofMinutes(5),
            0.0
        );
    }

    public ReliableMessagingService(
            OutboxRepository outbox,
            MessagePublisher publisher,
            Clock clock,
            String claimOwner,
            Duration leaseDuration,
            int maximumAttempts,
            Duration initialBackoff,
            Duration maximumBackoff,
            double jitterRatio) {
        this.outbox = Objects.requireNonNull(outbox);
        this.publisher = Objects.requireNonNull(publisher);
        this.clock = Objects.requireNonNull(clock);
        this.claimOwner = requireText(claimOwner, "claimOwner");
        if (leaseDuration == null
                || leaseDuration.isZero()
                || leaseDuration.isNegative()
                || leaseDuration.compareTo(Duration.ofMinutes(5)) > 0) {
            throw new DomainViolation("发件箱领取租约必须位于 0 到 5 分钟");
        }
        this.leaseDuration = leaseDuration;
        if (maximumAttempts < 1 || maximumAttempts > 100) {
            throw new DomainViolation("发件箱最大尝试次数必须位于 1 到 100");
        }
        if (initialBackoff == null
                || initialBackoff.isZero()
                || initialBackoff.isNegative()) {
            throw new DomainViolation("发件箱初始退避必须大于 0");
        }
        if (maximumBackoff == null
                || maximumBackoff.compareTo(initialBackoff) < 0
                || maximumBackoff.compareTo(Duration.ofHours(1)) > 0) {
            throw new DomainViolation("发件箱最大退避必须不小于初始退避且不超过 1 小时");
        }
        if (!Double.isFinite(jitterRatio)
                || jitterRatio < 0.0
                || jitterRatio > 0.5) {
            throw new DomainViolation("发件箱退避抖动比例必须位于 0 到 0.5");
        }
        this.maximumAttempts = maximumAttempts;
        this.initialBackoff = initialBackoff;
        this.maximumBackoff = maximumBackoff;
        this.jitterRatio = jitterRatio;
    }

    /**
     * RabbitMQ 确认之后才以领取者身份比较并交换为 PUBLISHED。
     * 确认成功而数据库写回失败时，租约到期会再次发布，消费者须由收件箱去重。
     */
    public int publishDue(int limit) {
        if (limit < 1 || limit > MAXIMUM_BATCH_SIZE) {
            throw new DomainViolation("发件箱批量大小必须位于 1 到 1000");
        }
        Instant now = Instant.now(clock);
        int published = 0;
        for (OutboxEvent event : outbox.claimBatch(
                now,
                limit,
                claimOwner,
                leaseDuration)) {
            try {
                publisher.publishAndConfirm(event);
                if (!outbox.markPublished(event.eventId(), claimOwner, Instant.now(clock))) {
                    throw new DomainViolation("发件箱发布确认状态发生并发冲突");
                }
                published++;
            } catch (RuntimeException error) {
                Instant failedAt = Instant.now(clock);
                String summary = summarize(error);
                if (error instanceof NonRetryableMessageException
                        || event.attemptCount() >= maximumAttempts) {
                    outbox.markDead(
                        event.eventId(),
                        claimOwner,
                        failedAt,
                        summary
                    );
                } else {
                    outbox.markFailed(
                        event.eventId(),
                        claimOwner,
                        failedAt.plus(backoff(event.attemptCount())),
                        summary
                    );
                }
            }
        }
        return published;
    }

    Duration backoff(int attemptCount) {
        int exponent = Math.max(0, Math.min(attemptCount - 1, 30));
        long multiplier = 1L << exponent;
        Duration raw;
        try {
            raw = initialBackoff.multipliedBy(multiplier);
        } catch (ArithmeticException overflow) {
            raw = maximumBackoff;
        }
        Duration bounded = raw.compareTo(maximumBackoff) > 0
            ? maximumBackoff
            : raw;
        if (jitterRatio == 0.0) {
            return bounded;
        }
        double factor = ThreadLocalRandom.current().nextDouble(
            1.0 - jitterRatio,
            1.0 + jitterRatio
        );
        long millis = Math.max(
            1,
            Math.min(
                maximumBackoff.toMillis(),
                Math.round(bounded.toMillis() * factor)
            )
        );
        return Duration.ofMillis(millis);
    }

    private static String summarize(RuntimeException error) {
        String type = error.getClass().getSimpleName();
        String message = error.getMessage();
        String summary = message == null || message.isBlank()
            ? type
            : type + ": " + message;
        return summary.length() <= 512 ? summary : summary.substring(0, 512);
    }

    private static String requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new DomainViolation(field + " 不能为空");
        }
        return value;
    }
}
