package com.tooldefect.business.storage.infrastructure;

import java.net.URI;
import java.time.Duration;
import java.util.Map;

/**
 * S3 协议客户端窄端口。实现可以绑定企业 S3、Ceph RGW 或受控开发替身。
 */
public interface S3ClientFacade {
    record HeadResult(
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

    record PresignedRequest(URI url, Map<String, String> headers) {}

    PresignedRequest presignPut(
            String bucket,
            String objectKey,
            long sizeBytes,
            String sha256,
            String mediaType,
            Map<String, String> metadata,
            Duration ttl);

    PresignedRequest presignGet(String bucket, String objectKey, Duration ttl);

    HeadResult headAndInspect(String bucket, String objectKey);
}
