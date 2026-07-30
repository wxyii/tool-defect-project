package com.tooldefect.business.shared.application;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Objects;

import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.messaging.OutboxEvent;

public final class ReliableMessagingService {
    private static final int MAXIMUM_BATCH_SIZE = 1_000;
    private static final Duration MAXIMUM_BACKOFF = Duration.ofMinutes(5);

    private final OutboxRepository outbox;
    private final MessagePublisher publisher;
    private final Clock clock;
    private final String claimOwner;
    private final Duration leaseDuration;

    public ReliableMessagingService(
            OutboxRepository outbox,
            MessagePublisher publisher,
            Clock clock,
            String claimOwner,
            Duration leaseDuration) {
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
                Instant retryAt = Instant.now(clock).plus(backoff(event.attemptCount()));
                outbox.markFailed(
                    event.eventId(),
                    claimOwner,
                    retryAt,
                    summarize(error)
                );
            }
        }
        return published;
    }

    static Duration backoff(int attemptCount) {
        int exponent = Math.max(0, Math.min(attemptCount - 1, 8));
        Duration delay = Duration.ofSeconds(1L << exponent);
        return delay.compareTo(MAXIMUM_BACKOFF) > 0 ? MAXIMUM_BACKOFF : delay;
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
