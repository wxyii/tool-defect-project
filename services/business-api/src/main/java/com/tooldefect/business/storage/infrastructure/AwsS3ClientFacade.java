package com.tooldefect.business.storage.infrastructure;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.Base64;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;

import com.tooldefect.business.storage.domain.StorageIntegrityViolation;

import software.amazon.awssdk.core.ResponseInputStream;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectResponse;
import software.amazon.awssdk.services.s3.model.HeadObjectRequest;
import software.amazon.awssdk.services.s3.model.NoSuchKeyException;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.s3.model.S3Exception;
import software.amazon.awssdk.services.s3.model.ServerSideEncryption;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
import software.amazon.awssdk.services.s3.presigner.model.GetObjectPresignRequest;
import software.amazon.awssdk.services.s3.presigner.model.PutObjectPresignRequest;

/**
 * AWS SDK v2 的 S3 兼容实现。对象确认会把内容流式落入限额临时文件，
 * 独立重算 SHA-256，再只读取图片头部获得解码尺寸。
 */
public final class AwsS3ClientFacade implements S3ClientFacade {
    private static final int BUFFER_SIZE = 64 * 1024;

    private final S3Client client;
    private final S3Presigner presigner;
    private final long maximumObjectBytes;
    private final long maximumPixels;
    private final long maximumDecodedBytes;

    public AwsS3ClientFacade(
            S3Client client,
            S3Presigner presigner,
            long maximumObjectBytes,
            long maximumPixels,
            long maximumDecodedBytes) {
        this.client = java.util.Objects.requireNonNull(client);
        this.presigner = java.util.Objects.requireNonNull(presigner);
        if (maximumObjectBytes <= 0
                || maximumPixels <= 0
                || maximumDecodedBytes <= 0) {
            throw new IllegalArgumentException("对象与解码限制必须大于 0");
        }
        this.maximumObjectBytes = maximumObjectBytes;
        this.maximumPixels = maximumPixels;
        this.maximumDecodedBytes = maximumDecodedBytes;
    }

    @Override
    public PresignedRequest presignPut(
            String bucket,
            String objectKey,
            long sizeBytes,
            String sha256,
            String mediaType,
            Map<String, String> metadata,
            Duration ttl) {
        PutObjectRequest put = PutObjectRequest.builder()
            .bucket(bucket)
            .key(objectKey)
            .contentLength(sizeBytes)
            .contentType(mediaType)
            .checksumSHA256(hexSha256ToBase64(sha256))
            .metadata(Map.copyOf(metadata))
            .serverSideEncryption(ServerSideEncryption.AES256)
            .build();
        var signed = presigner.presignPutObject(
            PutObjectPresignRequest.builder()
                .signatureDuration(ttl)
                .putObjectRequest(put)
                .build()
        );
        Map<String, String> headers = flattenClientHeaders(signed.signedHeaders());
        requireSigned(headers, "content-type");
        requireSigned(headers, "x-amz-checksum-sha256");
        requireSigned(headers, "x-amz-server-side-encryption");
        for (String metadataKey : metadata.keySet()) {
            requireSigned(headers, "x-amz-meta-" + metadataKey);
        }
        return new PresignedRequest(URI.create(signed.url().toString()), headers);
    }

    @Override
    public PresignedRequest presignGet(
            String bucket,
            String objectKey,
            Duration ttl) {
        var signed = presigner.presignGetObject(
            GetObjectPresignRequest.builder()
                .signatureDuration(ttl)
                .getObjectRequest(request -> request
                    .bucket(bucket)
                    .key(objectKey))
                .build()
        );
        return new PresignedRequest(
            URI.create(signed.url().toString()),
            flattenClientHeaders(signed.signedHeaders())
        );
    }

    @Override
    public HeadResult headAndInspect(String bucket, String objectKey) {
        try {
            var head = client.headObject(
                HeadObjectRequest.builder()
                    .bucket(bucket)
                    .key(objectKey)
                    .build()
            );
            if (head.contentLength() == null
                    || head.contentLength() <= 0
                    || head.contentLength() > maximumObjectBytes) {
                throw new StorageIntegrityViolation("对象压缩大小超过限制");
            }
            Path temporary = Files.createTempFile("td-object-inspection-", ".bin");
            try {
                String sha256 = downloadAndHash(
                    bucket,
                    objectKey,
                    temporary,
                    head.contentLength()
                );
                SafeImageInspector.Inspection inspection =
                    SafeImageInspector.inspect(
                        temporary,
                        head.contentType(),
                        maximumPixels,
                        maximumDecodedBytes
                    );
                return new HeadResult(
                    head.contentLength(),
                    sha256,
                    head.contentType(),
                    inspection.width(),
                    inspection.height(),
                    inspection.decodedBytes(),
                    head.versionId() == null ? "" : head.versionId(),
                    normalizeMetadata(head.metadata())
                );
            } finally {
                Files.deleteIfExists(temporary);
            }
        } catch (NoSuchKeyException error) {
            throw new StorageIntegrityViolation("对象不存在", error);
        } catch (S3Exception error) {
            if (error.statusCode() == 404) {
                throw new StorageIntegrityViolation("对象不存在", error);
            }
            throw new StorageIntegrityViolation("对象存储读取失败", error);
        } catch (ArithmeticException error) {
            throw new StorageIntegrityViolation("图片解码尺寸溢出", error);
        } catch (IOException error) {
            throw new StorageIntegrityViolation("对象检查失败", error);
        }
    }

    private String downloadAndHash(
            String bucket,
            String objectKey,
            Path target,
            long expectedSize) throws IOException {
        MessageDigest digest = sha256Digest();
        long total = 0;
        GetObjectRequest request = GetObjectRequest.builder()
            .bucket(bucket)
            .key(objectKey)
            .build();
        try (
            ResponseInputStream<GetObjectResponse> input = client.getObject(request);
            OutputStream output = Files.newOutputStream(target)
        ) {
            byte[] buffer = new byte[BUFFER_SIZE];
            int read;
            while ((read = input.read(buffer)) != -1) {
                total += read;
                if (total > maximumObjectBytes || total > expectedSize) {
                    throw new StorageIntegrityViolation("对象读取大小超过声明值");
                }
                digest.update(buffer, 0, read);
                output.write(buffer, 0, read);
            }
        }
        if (total != expectedSize) {
            throw new StorageIntegrityViolation("对象读取大小与 HEAD 不一致");
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    private static Map<String, String> flattenClientHeaders(
            Map<String, java.util.List<String>> signedHeaders) {
        Map<String, String> result = new LinkedHashMap<>();
        signedHeaders.forEach((name, values) -> {
            String normalized = name.toLowerCase(java.util.Locale.ROOT);
            if (!"host".equals(normalized)
                    && !"content-length".equals(normalized)
                    && !values.isEmpty()) {
                result.put(normalized, String.join(",", values));
            }
        });
        return Map.copyOf(result);
    }

    private static Map<String, String> normalizeMetadata(
            Map<String, String> metadata) {
        Map<String, String> normalized = new LinkedHashMap<>();
        metadata.forEach((name, value) -> {
            String key = name.toLowerCase(java.util.Locale.ROOT);
            if (normalized.putIfAbsent(key, value) != null) {
                throw new StorageIntegrityViolation("对象元数据键存在大小写碰撞");
            }
        });
        return Map.copyOf(normalized);
    }

    private static void requireSigned(Map<String, String> headers, String name) {
        if (!headers.containsKey(name)) {
            throw new StorageIntegrityViolation("预签名请求未绑定必要请求头：" + name);
        }
    }

    private static String hexSha256ToBase64(String sha256) {
        return Base64.getEncoder().encodeToString(HexFormat.of().parseHex(sha256));
    }

    private static MessageDigest sha256Digest() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("运行时缺少 SHA-256", impossible);
        }
    }
}
