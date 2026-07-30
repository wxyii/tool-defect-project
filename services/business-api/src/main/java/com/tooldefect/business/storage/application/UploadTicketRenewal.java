package com.tooldefect.business.storage.application;

import java.util.UUID;

/** API 层签发续传票据所依赖的最小应用端口。 */
@FunctionalInterface
public interface UploadTicketRenewal {
    ObjectStoragePort.UploadAuthorization renewRawUpload(
        UUID imageId,
        UUID captureId,
        UUID actorStationId,
        long sizeBytes,
        String sha256
    );
}
