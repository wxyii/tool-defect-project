package com.tooldefect.business.dataset.application;

import com.tooldefect.business.dataset.domain.DatasetNotFound;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;
import java.util.Objects;
import java.util.UUID;

@Service
public class DatasetQueryService {

    private final DatasetQueryRepository repository;

    public DatasetQueryService(DatasetQueryRepository repository) {
        this.repository = Objects.requireNonNull(repository);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> listDatasets(
            String actorId, int pageSize, String cursor) {
        return repository.listDatasets(actorId, pageSize, cursor);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> listVersions(String actorId, UUID datasetId, int pageSize, String cursor) {
        return repository.listVersions(actorId, datasetId, pageSize, cursor);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> listVersions(
            String actorId,
            UUID datasetId,
            String status,
            int pageSize,
            String cursor) {
        return repository.listVersions(
            actorId, datasetId, status, pageSize, cursor
        );
    }

    @Transactional(readOnly = true)
    public Map<String, Object> detailVersion(String actorId, UUID datasetVersionId) {
        return repository.detailVersion(actorId, datasetVersionId);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> listCandidates(String actorId, String status, int pageSize, String cursor) {
        return repository.listCandidates(actorId, status, pageSize, cursor);
    }

    @Transactional(readOnly = true)
    public Map<String, Object> diffVersions(UUID fromVersionId, UUID toVersionId) {
        return repository.diffVersions(fromVersionId, toVersionId);
    }
}
