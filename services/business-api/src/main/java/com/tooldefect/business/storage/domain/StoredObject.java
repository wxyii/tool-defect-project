package com.tooldefect.business.storage.domain;

import java.util.Objects;
import java.util.UUID;

import com.tooldefect.business.shared.domain.DomainViolation;

public final class StoredObject {
    private final UUID imageId;
    private final UUID captureId;
    private final UUID stationId;
    private final String bucket;
    private final String objectKey;
    private final long expectedSizeBytes;
    private final String expectedSha256;
    private final String expectedMediaType;
    private ObjectState state;
    private String objectVersion;
    private Integer width;
    private Integer height;
    private long recordVersion;

    public StoredObject(
            UUID imageId,
            UUID captureId,
            UUID stationId,
            String bucket,
            String objectKey,
            long expectedSizeBytes,
            String expectedSha256,
            String expectedMediaType) {
        this.imageId = Objects.requireNonNull(imageId);
        this.captureId = Objects.requireNonNull(captureId);
        this.stationId = Objects.requireNonNull(stationId);
        this.bucket = requireName(bucket, "bucket");
        this.objectKey = requireName(objectKey, "objectKey");
        if (expectedSizeBytes <= 0) {
            throw new DomainViolation("对象大小必须大于 0");
        }
        if (expectedSha256 == null || !expectedSha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("对象 SHA-256 不合法");
        }
        this.expectedSizeBytes = expectedSizeBytes;
        this.expectedSha256 = expectedSha256;
        this.expectedMediaType = requireName(expectedMediaType, "expectedMediaType");
        this.state = ObjectState.STAGING;
        this.objectVersion = "";
        this.recordVersion = 0;
    }

    private StoredObject(
            UUID imageId,
            UUID captureId,
            UUID stationId,
            String bucket,
            String objectKey,
            long expectedSizeBytes,
            String expectedSha256,
            String expectedMediaType,
            ObjectState state,
            String objectVersion,
            Integer width,
            Integer height,
            long recordVersion) {
        this.imageId = Objects.requireNonNull(imageId);
        this.captureId = Objects.requireNonNull(captureId);
        this.stationId = Objects.requireNonNull(stationId);
        this.bucket = requireName(bucket, "bucket");
        this.objectKey = requireName(objectKey, "objectKey");
        this.expectedSizeBytes = expectedSizeBytes;
        this.expectedSha256 = expectedSha256;
        this.expectedMediaType = requireName(expectedMediaType, "expectedMediaType");
        this.state = Objects.requireNonNull(state);
        this.objectVersion = objectVersion == null ? "" : objectVersion;
        this.width = width;
        this.height = height;
        this.recordVersion = recordVersion;
    }

    public static StoredObject restore(
            UUID imageId,
            UUID captureId,
            UUID stationId,
            String bucket,
            String objectKey,
            long expectedSizeBytes,
            String expectedSha256,
            String expectedMediaType,
            ObjectState state,
            String objectVersion,
            Integer width,
            Integer height,
            long recordVersion) {
        return new StoredObject(
            imageId,
            captureId,
            stationId,
            bucket,
            objectKey,
            expectedSizeBytes,
            expectedSha256,
            expectedMediaType,
            state,
            objectVersion,
            width,
            height,
            recordVersion
        );
    }

    public void confirm(
            long actualSizeBytes,
            String actualSha256,
            String actualMediaType,
            int actualWidth,
            int actualHeight,
            String actualObjectVersion) {
        if (state == ObjectState.AVAILABLE) {
            if (sameContent(
                    actualSizeBytes,
                    actualSha256,
                    actualMediaType,
                    actualWidth,
                    actualHeight)) {
                return;
            }
            throw new DomainViolation("已确认对象不能被不同内容覆盖");
        }
        if (state != ObjectState.STAGING) {
            throw new DomainViolation("只有 STAGING 对象可以确认");
        }
        if (!sameExpectedContent(actualSizeBytes, actualSha256, actualMediaType)
                || actualWidth <= 0
                || actualHeight <= 0) {
            throw new StorageIntegrityViolation("对象大小、媒体类型或 SHA-256 不一致");
        }
        state = ObjectState.AVAILABLE;
        width = actualWidth;
        height = actualHeight;
        objectVersion = actualObjectVersion == null ? "" : actualObjectVersion;
        recordVersion++;
    }

    public void requireAvailable() {
        if (state != ObjectState.AVAILABLE) {
            throw new DomainViolation("业务只能引用 AVAILABLE 对象");
        }
    }

    public void quarantine() {
        if (state == ObjectState.DELETED || state == ObjectState.ARCHIVED) {
            throw new DomainViolation("归档或删除对象不能重新隔离");
        }
        state = ObjectState.QUARANTINED;
        recordVersion++;
    }

    private boolean sameExpectedContent(
            long actualSizeBytes,
            String actualSha256,
            String actualMediaType) {
        return expectedSizeBytes == actualSizeBytes
            && expectedSha256.equals(actualSha256)
            && expectedMediaType.equalsIgnoreCase(actualMediaType);
    }

    private boolean sameContent(
            long actualSizeBytes,
            String actualSha256,
            String actualMediaType,
            int actualWidth,
            int actualHeight) {
        return sameExpectedContent(actualSizeBytes, actualSha256, actualMediaType)
            && Objects.equals(width, actualWidth)
            && Objects.equals(height, actualHeight);
    }

    private static String requireName(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new DomainViolation(field + " 不能为空");
        }
        return value;
    }

    public UUID imageId() {
        return imageId;
    }

    public UUID stationId() {
        return stationId;
    }

    public UUID captureId() {
        return captureId;
    }

    public String bucket() {
        return bucket;
    }

    public String objectKey() {
        return objectKey;
    }

    public long expectedSizeBytes() {
        return expectedSizeBytes;
    }

    public String expectedSha256() {
        return expectedSha256;
    }

    public String expectedMediaType() {
        return expectedMediaType;
    }

    public ObjectState state() {
        return state;
    }

    public String objectVersion() {
        return objectVersion;
    }

    public Integer width() {
        return width;
    }

    public Integer height() {
        return height;
    }

    public long recordVersion() {
        return recordVersion;
    }
}
