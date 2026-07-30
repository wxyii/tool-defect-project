package com.tooldefect.business.storage.infrastructure;

import java.util.UUID;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.storage.application.ReviewAnnotationStorage;

@Component
@ConditionalOnProperty(
    name = "td.storage.enabled",
    havingValue = "false",
    matchIfMissing = true
)
public final class UnavailableReviewAnnotationStorage
        implements ReviewAnnotationStorage {
    @Override
    public UploadTicket issue(
            UUID imageId,
            UUID reviewTaskId,
            UUID captureId,
            long sizeBytes,
            String sha256,
            int width,
            int height) {
        throw new DomainViolation("人工标注存储未配置");
    }

    @Override
    public ConfirmedAnnotation confirm(
            UUID reviewTaskId,
            UUID imageId,
            long sizeBytes,
            String sha256,
            String uploadReceipt) {
        throw new DomainViolation("人工标注存储未配置");
    }
}
