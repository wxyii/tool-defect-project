package com.tooldefect.business.model.application;

import com.tooldefect.business.model.domain.ModelVersion;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

public interface ModelRepository {

    Optional<ModelVersion> findVersion(UUID modelVersionId);

    void insertVersion(ModelVersion version);

    void updateVersion(ModelVersion version);

    void appendApproval(
            UUID approvalId,
            UUID modelVersionId,
            String stage,
            String decision,
            UUID actorId,
            String reason,
            Instant createdAt);

    Optional<ModelVersion> findLatestVersion(UUID modelId);

    Optional<ModelVersion> findVersionByRegistryName(String name, String version);

    record VersionSummary(
        UUID modelVersionId,
        UUID modelId,
        int version,
        String registryName,
        String registryVersion,
        String approvalState,
        UUID registeredBy,
        java.time.Instant createdAt
    ) {}
}
