package com.tooldefect.business.detection.application;

import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class DetectionQueryService {
    private final DetectionQueryRepository repository;

    public DetectionQueryService(DetectionQueryRepository repository) {
        this.repository = Objects.requireNonNull(repository);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> list(
            String actorId,
            String cursor,
            int pageSize,
            String businessDisposition,
            String algorithmOutcome,
            String modelVersion) {
        return repository.list(
            actorId,
            cursor,
            pageSize,
            businessDisposition,
            algorithmOutcome,
            modelVersion
        );
    }

    @Transactional(readOnly = true)
    public Map<String, Object> detail(
            String actorId,
            UUID detectionTaskId) {
        return repository.detail(actorId, detectionTaskId);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> reviewEvidence(
            String actorId,
            UUID captureId) {
        return repository.detailByCapture(
            actorId,
            captureId,
            "review:read"
        );
    }
}
