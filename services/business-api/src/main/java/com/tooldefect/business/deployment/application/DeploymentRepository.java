package com.tooldefect.business.deployment.application;

import com.tooldefect.business.deployment.domain.DeploymentApprovalRole;
import com.tooldefect.business.deployment.domain.ModelDeployment;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

public interface DeploymentRepository {

    Optional<ModelDeployment> findDeployment(UUID deploymentId);

    void insertDeployment(ModelDeployment deployment);

    void updateDeployment(ModelDeployment deployment);

    void appendApproval(
            UUID approvalId,
            UUID deploymentId,
            DeploymentApprovalRole role,
            String decision,
            UUID actorId,
            String reason,
            Instant createdAt);

    record DeploymentSummary(
        UUID deploymentId,
        UUID modelVersionId,
        String environment,
        String strategy,
        String status,
        UUID approvedBy,
        java.time.Instant createdAt
    ) {}
}
