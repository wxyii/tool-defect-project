package com.tooldefect.business.model.domain;

import java.util.Objects;
import java.util.UUID;

public final class ModelNotFound extends RuntimeException {
    private final UUID modelVersionId;

    public ModelNotFound(UUID modelVersionId) {
        super("模型版本未找到: " + modelVersionId);
        this.modelVersionId = Objects.requireNonNull(modelVersionId);
    }

    public ModelNotFound(String message) {
        super(message);
        this.modelVersionId = null;
    }

    public UUID modelVersionId() {
        return modelVersionId;
    }
}
