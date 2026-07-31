package com.tooldefect.business.model.application;

import java.util.Map;
import java.util.UUID;

public interface ModelQueryRepository {

    Map<String, Object> listVersions(String actorId, UUID modelId, int pageSize, String cursor);

    Map<String, Object> detailVersion(String actorId, UUID modelVersionId);

    Map<String, Object> listByState(String actorId, String approvalState, int pageSize, String cursor);
}
