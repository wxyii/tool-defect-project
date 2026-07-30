package com.tooldefect.business.storage.application;

import java.util.Optional;
import java.util.UUID;

import com.tooldefect.business.storage.domain.StoredObject;

public interface StoredObjectRepository {
    Optional<StoredObject> findById(UUID imageId);

    Optional<StoredObject> findByIdForUpdate(UUID imageId);

    void insertStaging(StoredObject object);

    boolean captureBelongsToStation(UUID captureId, UUID stationId);

    boolean markAvailable(
            UUID imageId,
            long expectedRecordVersion,
            String objectVersion,
            int width,
            int height);

    boolean markQuarantined(
            UUID imageId,
            long expectedRecordVersion,
            String reason);
}
