package com.tooldefect.business.storage.application;

import java.util.Optional;
import java.util.UUID;

import com.tooldefect.business.storage.domain.StoredObject;

public interface StoredObjectRepository {
    Optional<StoredObject> findById(UUID imageId);

    Optional<StoredObject> findByIdForUpdate(UUID imageId);

    void insertStaging(StoredObject object);

    void insertReviewMaskStaging(
        StoredObject object,
        UUID reviewTaskId,
        int expectedWidth,
        int expectedHeight
    );

    default void insertDerivedAvailable(
            DerivedObjectAcceptance.DerivedObject object,
            String actualObjectVersion,
            int width,
            int height) {
        throw new UnsupportedOperationException("派生对象仓储尚未实现");
    }

    boolean captureBelongsToStation(UUID captureId, UUID stationId);

    Optional<ReviewMaskSource> reviewMaskSource(
        UUID reviewTaskId,
        UUID captureId
    );

    Optional<ReviewMaskExpectation> reviewMaskExpectation(UUID imageId);

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

    record ReviewMaskSource(
        UUID stationId,
        int width,
        int height
    ) {
    }

    record ReviewMaskExpectation(
        UUID reviewTaskId,
        int width,
        int height
    ) {
    }
}
