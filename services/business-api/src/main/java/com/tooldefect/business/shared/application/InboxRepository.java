package com.tooldefect.business.shared.application;

import java.time.Duration;
import java.time.Instant;
import java.util.UUID;

import com.tooldefect.business.shared.messaging.InboxReceipt;

public interface InboxRepository {
    enum Decision {
        PROCESS,
        ALREADY_PROCESSED,
        BUSY
    }

    record Claim(Decision decision, InboxReceipt receipt) {
    }

    Claim claim(
        String messageId,
        String consumer,
        UUID detectionTaskId,
        String resultSha256,
        String claimOwner,
        Instant now,
        Duration leaseDuration
    );

    boolean markProcessed(
        String messageId,
        String consumer,
        String claimOwner,
        Instant processedAt
    );
}
