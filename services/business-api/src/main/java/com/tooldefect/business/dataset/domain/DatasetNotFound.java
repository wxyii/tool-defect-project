package com.tooldefect.business.dataset.domain;

import java.util.Objects;
import java.util.UUID;

public final class DatasetNotFound extends RuntimeException {
    private final UUID datasetVersionId;

    public DatasetNotFound(UUID datasetVersionId) {
        super("数据集版本未找到: " + datasetVersionId);
        this.datasetVersionId = Objects.requireNonNull(datasetVersionId);
    }

    public UUID datasetVersionId() {
        return datasetVersionId;
    }

    public DatasetNotFound(String message) {
        super(message);
        this.datasetVersionId = null;
    }
}
