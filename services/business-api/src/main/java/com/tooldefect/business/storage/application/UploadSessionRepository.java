package com.tooldefect.business.storage.application;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import com.tooldefect.business.storage.domain.UploadSession;

public interface UploadSessionRepository {
    Optional<UploadSession> findLatest(UUID imageId);

    Optional<UploadSession> findLatestForUpdate(UUID imageId);

    long countFailed(UUID imageId);

    void revokeIssued(UUID imageId, String reason);

    void insert(UploadSession session);

    boolean markConfirmed(UUID uploadSessionId, Instant confirmedAt);

    boolean markExpired(UUID uploadSessionId);

    boolean markFailed(UUID uploadSessionId, String failureCode);
}
