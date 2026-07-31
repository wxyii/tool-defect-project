package com.tooldefect.business.dataset.application;

import java.util.Map;
import java.util.UUID;

public interface DatasetQueryRepository {

    Map<String, Object> listVersions(String actorId, UUID datasetId, int pageSize, String cursor);

    Map<String, Object> detailVersion(String actorId, UUID datasetVersionId);

    Map<String, Object> listCandidates(String actorId, String status, int pageSize, String cursor);

    Map<String, Object> diffVersions(UUID fromVersionId, UUID toVersionId);
}
