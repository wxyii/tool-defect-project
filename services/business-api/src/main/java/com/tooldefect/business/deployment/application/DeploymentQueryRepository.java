package com.tooldefect.business.deployment.application;

import java.util.Map;
import java.util.UUID;

public interface DeploymentQueryRepository {

    Map<String, Object> listDeployments(String actorId, UUID modelVersionId, int pageSize, String cursor);

    Map<String, Object> detailDeployment(String actorId, UUID deploymentId);

    Map<String, Object> listByStatus(String actorId, String status, int pageSize, String cursor);
}
