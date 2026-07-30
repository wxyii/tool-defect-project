package com.tooldefect.business.storage.application;

import java.time.Clock;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.audit.domain.AuditRecord;
import com.tooldefect.business.shared.application.Uuid7Generator;

@Service
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
public class ImageAccessService {
    private final StorageApplicationService storage;
    private final AuditTrail audit;
    private final Uuid7Generator ids;
    private final Clock clock;

    public ImageAccessService(
            StorageApplicationService storage,
            AuditTrail audit,
            Uuid7Generator ids,
            Clock clock) {
        this.storage = Objects.requireNonNull(storage);
        this.audit = Objects.requireNonNull(audit);
        this.ids = Objects.requireNonNull(ids);
        this.clock = Objects.requireNonNull(clock);
    }

    @Transactional
    public StorageApplicationService.ReadAuthorization issue(
            UUID imageId,
            String actorId,
            String purpose,
            String requestId,
            String traceId) {
        var authorization = storage.issueReadAuthorization(
            imageId,
            actorId,
            purpose
        );
        Instant now = Instant.now(clock);
        audit.append(new AuditRecord(
            ids.next(),
            now,
            "USER",
            actorId,
            "DOWNLOAD".equals(purpose)
                ? "image.original.download"
                : "image.view",
            "image_object",
            imageId.toString(),
            null,
            null,
            purpose,
            requestId,
            traceId,
            "SUCCESS",
            null
        ));
        return authorization;
    }
}
