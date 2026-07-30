package com.tooldefect.business.shared.application;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import com.tooldefect.business.shared.messaging.OutboxEvent;

public interface OutboxRepository {
    void append(OutboxEvent event);

    List<OutboxEvent> claimBatch(
        Instant now,
        int limit,
        String claimOwner,
        Duration leaseDuration
    );

    boolean markPublished(UUID eventId, String claimOwner, Instant publishedAt);

    boolean markFailed(
        UUID eventId,
        String claimOwner,
        Instant retryAt,
        String errorSummary
    );

    boolean markDead(
        UUID eventId,
        String claimOwner,
        Instant failedAt,
        String errorSummary
    );

    boolean exists(UUID eventId);
}
