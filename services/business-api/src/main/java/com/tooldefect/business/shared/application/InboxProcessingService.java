package com.tooldefect.business.shared.application;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

import org.springframework.transaction.support.TransactionTemplate;

import com.tooldefect.business.shared.domain.DomainViolation;

/**
 * 收件箱领取、业务效果和完成标记共用一个数据库事务。因此队列可以至少一次
 * 投递，而持久化业务效果仍至多一次。
 */
public final class InboxProcessingService {
    public enum Result {
        PROCESSED,
        ALREADY_PROCESSED,
        BUSY
    }

    @FunctionalInterface
    public interface TransactionalEffect {
        void apply();
    }

    private final InboxRepository inbox;
    private final TransactionTemplate transactions;
    private final Clock clock;
    private final String claimOwner;
    private final Duration leaseDuration;

    public InboxProcessingService(
            InboxRepository inbox,
            TransactionTemplate transactions,
            Clock clock,
            String claimOwner,
            Duration leaseDuration) {
        this.inbox = Objects.requireNonNull(inbox);
        this.transactions = Objects.requireNonNull(transactions);
        this.clock = Objects.requireNonNull(clock);
        this.claimOwner = requireText(claimOwner, "claimOwner");
        if (leaseDuration == null || leaseDuration.isZero() || leaseDuration.isNegative()) {
            throw new DomainViolation("收件箱领取租约必须大于 0");
        }
        this.leaseDuration = leaseDuration;
    }

    public Result process(
            String messageId,
            String consumer,
            UUID detectionTaskId,
            String resultSha256,
            TransactionalEffect effect) {
        Objects.requireNonNull(effect);
        return transactions.execute(status -> {
            Instant now = Instant.now(clock);
            InboxRepository.Claim claim = inbox.claim(
                messageId,
                consumer,
                detectionTaskId,
                resultSha256,
                claimOwner,
                now,
                leaseDuration
            );
            return switch (claim.decision()) {
                case ALREADY_PROCESSED -> Result.ALREADY_PROCESSED;
                case BUSY -> Result.BUSY;
                case PROCESS -> {
                    effect.apply();
                    if (!inbox.markProcessed(
                            claim.receipt().messageId(),
                            claim.receipt().consumer(),
                            claimOwner,
                            Instant.now(clock))) {
                        throw new DomainViolation("收件箱完成状态发生并发冲突");
                    }
                    yield Result.PROCESSED;
                }
            };
        });
    }

    private static String requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new DomainViolation(field + " 不能为空");
        }
        return value;
    }
}
