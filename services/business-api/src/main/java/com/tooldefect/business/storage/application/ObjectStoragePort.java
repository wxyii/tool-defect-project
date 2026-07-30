package com.tooldefect.business.storage.application;

import java.net.URI;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;

public interface ObjectStoragePort {
    record ObjectHead(
            long sizeBytes,
            String sha256,
            String mediaType,
            int width,
            int height,
            long decodedBytes,
            int bands,
            boolean binaryMask,
            String objectVersion,
            Map<String, String> metadata) {}

    record UploadAuthorization(
            String method,
            URI url,
            Map<String, String> headers,
            Instant expiresAt,
            String uploadReceipt) {

        public UploadAuthorization withUploadReceipt(String receipt) {
            return new UploadAuthorization(method, url, headers, expiresAt, receipt);
        }
    }

    UploadAuthorization authorizeUpload(
            String bucket,
            String objectKey,
            long sizeBytes,
            String sha256,
            String mediaType,
            Map<String, String> metadata,
            Duration ttl);

    ObjectHead head(String bucket, String objectKey);

    URI authorizeRead(String bucket, String objectKey, Duration ttl);
}
