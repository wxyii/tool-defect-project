package com.tooldefect.business.deployment.domain;

import java.util.Objects;
import java.util.UUID;

public final class DeploymentNotFound extends RuntimeException {
    private final UUID deploymentId;

    public DeploymentNotFound(UUID deploymentId) {
        super("模型部署未找到: " + deploymentId);
        this.deploymentId = Objects.requireNonNull(deploymentId);
    }

    public DeploymentNotFound(String message) {
        super(message);
        this.deploymentId = null;
    }

    public UUID deploymentId() {
        return deploymentId;
    }
}
