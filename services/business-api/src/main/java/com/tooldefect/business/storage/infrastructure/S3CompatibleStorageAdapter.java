package com.tooldefect.business.storage.infrastructure;

import java.net.URI;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.Objects;

import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.storage.application.ObjectStoragePort;

/**
 * 不泄露长期凭据的 S3 兼容适配器。
 */
public final class S3CompatibleStorageAdapter implements ObjectStoragePort {
    private final S3ClientFacade client;
    private final Clock clock;

    public S3CompatibleStorageAdapter(
            S3ClientFacade client,
            Clock clock) {
        this.client = Objects.requireNonNull(client);
        this.clock = Objects.requireNonNull(clock);
    }

    @Override
    public UploadAuthorization authorizeUpload(
            String bucket,
            String objectKey,
            long sizeBytes,
            String sha256,
            String mediaType,
            Map<String, String> metadata,
            Duration ttl) {
        requireObjectLocation(bucket, objectKey);
        requireUploadShape(sizeBytes, sha256, mediaType, metadata);
        S3ClientFacade.PresignedRequest request = client.presignPut(
            bucket,
            objectKey,
            sizeBytes,
            sha256,
            mediaType,
            metadata,
            ttl
        );
        requireSafeUri(request.url());
        return new UploadAuthorization(
            "PUT",
            request.url(),
            Map.copyOf(request.headers()),
            Instant.now(clock).plus(ttl),
            null
        );
    }

    @Override
    public ObjectHead head(String bucket, String objectKey) {
        requireObjectLocation(bucket, objectKey);
        S3ClientFacade.HeadResult result = client.headAndInspect(bucket, objectKey);
        return new ObjectHead(
            result.sizeBytes(),
            result.sha256(),
            result.mediaType(),
            result.width(),
            result.height(),
            result.decodedBytes(),
            result.bands(),
            result.binaryMask(),
            result.objectVersion(),
            Map.copyOf(result.metadata())
        );
    }

    @Override
    public URI authorizeRead(String bucket, String objectKey, Duration ttl) {
        requireObjectLocation(bucket, objectKey);
        URI uri = client.presignGet(bucket, objectKey, ttl).url();
        requireSafeUri(uri);
        return uri;
    }

    private void requireSafeUri(URI uri) {
        if (uri == null || uri.getHost() == null) {
            throw new DomainViolation("签名地址必须是绝对网络地址");
        }
        if (!"https".equalsIgnoreCase(uri.getScheme())) {
            throw new DomainViolation("签名地址必须使用 HTTPS");
        }
        if (uri.getUserInfo() != null) {
            throw new DomainViolation("签名地址不能嵌入用户凭据");
        }
    }

    private static void requireObjectLocation(String bucket, String objectKey) {
        if (bucket == null || !bucket.matches("[a-z0-9][a-z0-9.-]{1,62}")) {
            throw new DomainViolation("桶名不合法");
        }
        if (objectKey == null
                || !objectKey.matches("[a-z0-9/_\\.-]+")
                || objectKey.contains("..")
                || objectKey.startsWith("/")) {
            throw new DomainViolation("对象键不合法");
        }
    }

    private static void requireUploadShape(
            long sizeBytes,
            String sha256,
            String mediaType,
            Map<String, String> metadata) {
        if (sizeBytes <= 0) {
            throw new DomainViolation("对象大小必须大于 0");
        }
        if (sha256 == null || !sha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("对象 SHA-256 不合法");
        }
        if (mediaType == null || mediaType.isBlank()) {
            throw new DomainViolation("对象媒体类型不能为空");
        }
        if (metadata == null || metadata.values().stream().anyMatch(Objects::isNull)) {
            throw new DomainViolation("对象元数据不合法");
        }
    }
}
