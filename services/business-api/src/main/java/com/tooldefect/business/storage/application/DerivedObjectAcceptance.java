package com.tooldefect.business.storage.application;

import java.util.Map;
import java.util.UUID;

public interface DerivedObjectAcceptance {
    void confirmDerived(DerivedObject object);

    record DerivedObject(
        UUID imageId,
        UUID captureId,
        UUID detectionTaskId,
        String kind,
        String bucket,
        String objectKey,
        String objectVersion,
        String sha256,
        long sizeBytes,
        String mediaType,
        Map<String, Object> metadata
    ) {
        public DerivedObject {
            metadata = Map.copyOf(metadata);
        }
    }
}
