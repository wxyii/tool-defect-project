package com.tooldefect.business.storage.application;

import java.net.URI;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.Base64;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.storage.domain.ObjectState;
import com.tooldefect.business.storage.domain.StorageAccessDenied;
import com.tooldefect.business.storage.domain.StorageIntegrityViolation;
import com.tooldefect.business.storage.domain.StorageTicketExpired;
import com.tooldefect.business.storage.domain.StoredObject;
import com.tooldefect.business.storage.domain.UploadSession;
import com.tooldefect.business.storage.domain.UploadSessionStatus;

public class StorageApplicationService
        implements UploadTicketRenewal,
            DerivedObjectAcceptance,
            ReviewAnnotationStorage {
    public static final String META_RECEIPT_SHA256 = "td-receipt-sha256";
    public static final String META_CONTENT_SHA256 = "td-content-sha256";
    public static final String META_CAPTURE_ID = "td-capture-id";
    public static final String META_STATION_ID = "td-station-id";
    public static final String UPLOAD_RECEIPT_HEADER =
        "X-Tool-Defect-Upload-Receipt";
    private static final Set<String> EDGE_MEDIA_TYPES = Set.of(
        "image/png", "image/jpeg", "image/tiff"
    );

    private final StoredObjectRepository repository;
    private final UploadSessionRepository sessions;
    private final ObjectStoragePort storage;
    private final StationScopeAuthorizer authorizer;
    private final ObjectKeyPolicy objectKeyPolicy;
    private final Clock clock;
    private final SecureRandom secureRandom;
    private final String rawBucket;
    private final String derivedBucket;
    private final String reviewBucket;
    private final Duration uploadTtl;
    private final Duration readTtl;
    private final long maximumObjectBytes;
    private final long maximumPixels;
    private final long maximumDecodedBytes;

    public StorageApplicationService(
            StoredObjectRepository repository,
            UploadSessionRepository sessions,
            ObjectStoragePort storage,
            StationScopeAuthorizer authorizer,
            ObjectKeyPolicy objectKeyPolicy,
            Clock clock,
            SecureRandom secureRandom,
            String rawBucket,
            String derivedBucket,
            String reviewBucket,
            Duration uploadTtl,
            Duration readTtl,
            long maximumObjectBytes,
            long maximumPixels,
            long maximumDecodedBytes) {
        this.repository = Objects.requireNonNull(repository);
        this.sessions = Objects.requireNonNull(sessions);
        this.storage = Objects.requireNonNull(storage);
        this.authorizer = Objects.requireNonNull(authorizer);
        this.objectKeyPolicy = Objects.requireNonNull(objectKeyPolicy);
        this.clock = Objects.requireNonNull(clock);
        this.secureRandom = Objects.requireNonNull(secureRandom);
        this.rawBucket = requireText(rawBucket, "原图桶");
        this.derivedBucket = requireText(derivedBucket, "派生对象桶");
        this.reviewBucket = requireText(reviewBucket, "人工标注桶");
        this.uploadTtl = requireShortTtl(uploadTtl, "上传");
        this.readTtl = requireShortTtl(readTtl, "读取");
        if (maximumObjectBytes <= 0 || maximumPixels <= 0 || maximumDecodedBytes <= 0) {
            throw new DomainViolation("解码限制必须大于 0");
        }
        this.maximumObjectBytes = maximumObjectBytes;
        this.maximumPixels = maximumPixels;
        this.maximumDecodedBytes = maximumDecodedBytes;
    }

    @Transactional
    public ObjectStoragePort.UploadAuthorization issueRawUpload(
            UUID imageId,
            UUID captureId,
            UUID objectStationId,
            UUID actorStationId,
            LocalDate capturedDate,
            String imageRole,
            long sizeBytes,
            String sha256,
            String mediaType,
            String extension) {
        Objects.requireNonNull(imageId);
        Objects.requireNonNull(captureId);
        Objects.requireNonNull(objectStationId);
        Objects.requireNonNull(actorStationId);
        Objects.requireNonNull(capturedDate);
        requireEdgeMediaType(mediaType, extension);
        if (sizeBytes <= 0 || sizeBytes > maximumObjectBytes) {
            throw new DomainViolation("对象大小超过允许范围");
        }
        if (!authorizer.mayWrite(actorStationId, objectStationId)) {
            throw new StorageAccessDenied("设备无权写入其他工位对象");
        }
        if (!repository.captureBelongsToStation(captureId, objectStationId)) {
            throw new DomainViolation("采集事件不属于声明工位");
        }

        String key = objectKeyPolicy.rawKey(
            capturedDate,
            objectStationId,
            captureId,
            imageRole,
            sha256,
            extension
        );
        StoredObject object = new StoredObject(
            imageId,
            captureId,
            objectStationId,
            rawBucket,
            key,
            sizeBytes,
            sha256,
            mediaType
        );
        var existing = repository.findById(imageId);
        if (existing.isEmpty()) {
            repository.insertStaging(object);
        } else {
            requireSameStagingRegistration(existing.get(), object);
            object = existing.get();
            sessions.revokeIssued(imageId, "REISSUED");
        }

        return issueSession(object);
    }

    /**
     * 为冻结契约中的续签端点签发新票据。对象位置、媒体类型和工位范围均从
     * 首次登记恢复，请求方只能重复声明已经登记的大小和 SHA-256。
     */
    @Transactional
    @Override
    public ObjectStoragePort.UploadAuthorization renewRawUpload(
            UUID imageId,
            UUID captureId,
            UUID actorStationId,
            long sizeBytes,
            String sha256) {
        StoredObject object = repository.findByIdForUpdate(
                Objects.requireNonNull(imageId))
            .orElseThrow(() -> new DomainViolation("图片记录不存在"));
        if (!object.captureId().equals(Objects.requireNonNull(captureId))) {
            throw new DomainViolation("图片不属于声明的采集事件");
        }
        if (object.state() != ObjectState.STAGING) {
            throw new DomainViolation("只有 STAGING 对象可以续签上传票据");
        }
        if (!authorizer.mayWrite(
                Objects.requireNonNull(actorStationId),
                object.stationId())) {
            throw new StorageAccessDenied("设备无权续签其他工位对象");
        }
        if (!repository.captureBelongsToStation(captureId, object.stationId())) {
            throw new DomainViolation("采集事件与对象工位绑定失效");
        }
        if (sizeBytes != object.expectedSizeBytes()
                || !object.expectedSha256().equals(sha256)) {
            throw new DomainViolation("续签请求与原始对象登记冲突");
        }
        sessions.revokeIssued(imageId, "RENEWED");
        return issueSession(object);
    }

    @Override
    @Transactional
    public ReviewAnnotationStorage.UploadTicket issue(
            UUID imageId,
            UUID reviewTaskId,
            UUID captureId,
            long sizeBytes,
            String sha256,
            int width,
            int height) {
        if (sizeBytes <= 0 || sizeBytes > maximumObjectBytes) {
            throw new DomainViolation("人工掩膜大小超过允许范围");
        }
        long pixels;
        try {
            pixels = Math.multiplyExact((long) width, (long) height);
        } catch (ArithmeticException invalid) {
            throw new DomainViolation("人工掩膜尺寸溢出", invalid);
        }
        if (width <= 0 || height <= 0 || pixels > maximumPixels) {
            throw new DomainViolation("人工掩膜尺寸超过允许范围");
        }
        var source = repository.reviewMaskSource(reviewTaskId, captureId)
            .orElseThrow(() ->
                new DomainViolation("复核任务缺少可用原图或不允许标注")
            );
        if (source.width() != width || source.height() != height) {
            throw new StorageIntegrityViolation("人工掩膜尺寸必须与原图一致");
        }
        String key = objectKeyPolicy.reviewMaskKey(
            LocalDate.now(clock),
            reviewTaskId,
            imageId,
            sha256
        );
        StoredObject object = new StoredObject(
            imageId,
            captureId,
            source.stationId(),
            reviewBucket,
            key,
            sizeBytes,
            sha256,
            "image/png"
        );
        var existing = repository.findById(imageId);
        if (existing.isEmpty()) {
            repository.insertReviewMaskStaging(
                object,
                reviewTaskId,
                width,
                height
            );
        } else {
            requireSameStagingRegistration(existing.get(), object);
            var expectation = repository.reviewMaskExpectation(imageId)
                .orElseThrow(() ->
                    new DomainViolation("同一 imageId 已用于其他图片类型")
                );
            if (!expectation.reviewTaskId().equals(reviewTaskId)
                    || expectation.width() != width
                    || expectation.height() != height) {
                throw new DomainViolation("同一 imageId 的人工掩膜登记冲突");
            }
            object = existing.get();
            sessions.revokeIssued(imageId, "REISSUED");
        }
        ObjectStoragePort.UploadAuthorization ticket = issueSession(object);
        return new ReviewAnnotationStorage.UploadTicket(
            imageId,
            ticket.method(),
            ticket.url(),
            ticket.headers(),
            ticket.expiresAt()
        );
    }

    private ObjectStoragePort.UploadAuthorization issueSession(StoredObject object) {
        String receipt = newReceipt();
        String receiptSha256 = sha256(receipt);
        Instant expiresAt = Instant.now(clock).plus(uploadTtl);
        UploadSession session = new UploadSession(
            UUID.randomUUID(),
            object.imageId(),
            object.captureId(),
            object.stationId(),
            receiptSha256,
            object.expectedSizeBytes(),
            object.expectedSha256(),
            object.expectedMediaType(),
            UploadSessionStatus.ISSUED,
            expiresAt
        );
        sessions.insert(session);

        Map<String, String> metadata = Map.of(
            META_RECEIPT_SHA256, receiptSha256,
            META_CONTENT_SHA256, object.expectedSha256(),
            META_CAPTURE_ID, object.captureId().toString(),
            META_STATION_ID, object.stationId().toString()
        );
        ObjectStoragePort.UploadAuthorization authorization = storage.authorizeUpload(
            object.bucket(),
            object.objectKey(),
            object.expectedSizeBytes(),
            object.expectedSha256(),
            object.expectedMediaType(),
            metadata,
            uploadTtl
        );
        Map<String, String> responseHeaders = new LinkedHashMap<>(
            authorization.headers()
        );
        responseHeaders.put(UPLOAD_RECEIPT_HEADER, receipt);
        if (responseHeaders.size() > 8) {
            throw new StorageIntegrityViolation("上传授权头超过 v1 契约上限");
        }
        return new ObjectStoragePort.UploadAuthorization(
            authorization.method(),
            authorization.url(),
            Map.copyOf(responseHeaders),
            authorization.expiresAt(),
            receipt
        );
    }

    @Transactional(noRollbackFor = {
        StorageIntegrityViolation.class,
        StorageTicketExpired.class
    })
    public StoredObject confirm(
            UUID imageId,
            UUID captureId,
            UUID actorStationId,
            long requestSizeBytes,
            String requestSha256,
            String uploadReceipt) {
        StoredObject object = repository.findByIdForUpdate(imageId)
            .orElseThrow(() -> new DomainViolation("图片记录不存在"));
        if (!object.captureId().equals(captureId)) {
            throw new DomainViolation("图片不属于声明的采集事件");
        }
        if (!authorizer.mayWrite(actorStationId, object.stationId())) {
            throw new StorageAccessDenied("设备无权确认其他工位对象");
        }
        return confirmStoredObject(
            object,
            requestSizeBytes,
            requestSha256,
            uploadReceipt,
            null
        );
    }

    @Override
    @Transactional(noRollbackFor = {
        StorageIntegrityViolation.class,
        StorageTicketExpired.class
    })
    public ReviewAnnotationStorage.ConfirmedAnnotation confirm(
            UUID reviewTaskId,
            UUID imageId,
            long requestSizeBytes,
            String requestSha256,
            String uploadReceipt) {
        StoredObject object = repository.findByIdForUpdate(imageId)
            .orElseThrow(() -> new DomainViolation("人工掩膜记录不存在"));
        var expectation = repository.reviewMaskExpectation(imageId)
            .orElseThrow(() -> new DomainViolation("图片不是人工掩膜"));
        if (!expectation.reviewTaskId().equals(reviewTaskId)) {
            throw new StorageAccessDenied("人工掩膜不属于声明复核任务");
        }
        StoredObject confirmed = confirmStoredObject(
            object,
            requestSizeBytes,
            requestSha256,
            uploadReceipt,
            expectation
        );
        return new ReviewAnnotationStorage.ConfirmedAnnotation(
            confirmed.imageId(),
            confirmed.expectedSha256()
        );
    }

    private StoredObject confirmStoredObject(
            StoredObject object,
            long requestSizeBytes,
            String requestSha256,
            String uploadReceipt,
            StoredObjectRepository.ReviewMaskExpectation maskExpectation) {
        UploadSession session = sessions.findLatestForUpdate(object.imageId())
            .orElseThrow(() -> new DomainViolation("上传会话不存在"));
        String receiptSha256 = sha256(requireText(uploadReceipt, "上传回执"));
        if (!session.receiptMatches(receiptSha256)
                || !session.captureId().equals(object.captureId())
                || !session.stationId().equals(object.stationId())) {
            throw new DomainViolation("上传回执或资源范围不匹配");
        }
        if (!session.requestMatches(requestSizeBytes, requestSha256)) {
            throw new DomainViolation("重复确认的大小或 SHA-256 与原请求冲突");
        }
        Instant now = Instant.now(clock);
        if (session.status() == UploadSessionStatus.ISSUED && session.expiredAt(now)) {
            sessions.markExpired(session.uploadSessionId());
            throw new StorageTicketExpired("上传授权已过期，必须重新申请");
        }
        if (session.status() != UploadSessionStatus.ISSUED
                && session.status() != UploadSessionStatus.CONFIRMED) {
            throw new DomainViolation("上传会话当前不可确认");
        }

        ObjectStoragePort.ObjectHead head;
        try {
            head = storage.head(object.bucket(), object.objectKey());
        } catch (StorageIntegrityViolation error) {
            recordIntegrityFailure(
                object,
                session,
                "OBJECT_MISSING_OR_UNREADABLE"
            );
            throw error;
        }
        try {
            requireBoundMetadata(head.metadata(), session);
        } catch (StorageIntegrityViolation error) {
            recordIntegrityFailure(
                object,
                session,
                "UPLOAD_METADATA_MISMATCH"
            );
            throw error;
        }
        long pixels;
        try {
            pixels = Math.multiplyExact((long) head.width(), (long) head.height());
        } catch (ArithmeticException error) {
            recordIntegrityFailure(
                object,
                session,
                "DECODE_DIMENSION_OVERFLOW"
            );
            throw new StorageIntegrityViolation("图片解码尺寸溢出", error);
        }
        if (head.width() <= 0 || head.height() <= 0
                || pixels > maximumPixels
                || head.decodedBytes() <= 0
                || head.decodedBytes() > maximumDecodedBytes) {
            recordIntegrityFailure(object, session, "DECODE_LIMIT_EXCEEDED");
            throw new StorageIntegrityViolation("图片解码后尺寸超过限制");
        }
        if (maskExpectation != null
                && (
                    head.width() != maskExpectation.width()
                    || head.height() != maskExpectation.height()
                    || head.bands() != 1
                    || !head.binaryMask()
                    || !"image/png".equalsIgnoreCase(head.mediaType())
                )) {
            recordIntegrityFailure(
                object,
                session,
                "REVIEW_MASK_FORMAT_INVALID"
            );
            throw new StorageIntegrityViolation(
                "人工掩膜必须与原图同尺寸、单通道且值域为 0/255"
            );
        }
        long originalVersion = object.recordVersion();
        try {
            object.confirm(
                head.sizeBytes(),
                head.sha256(),
                head.mediaType(),
                head.width(),
                head.height(),
                head.objectVersion()
            );
        } catch (DomainViolation error) {
            recordIntegrityFailure(object, session, "CONTENT_CONFLICT");
            throw new StorageIntegrityViolation("对象确认内容冲突", error);
        }
        if (object.state() == ObjectState.AVAILABLE
                && object.recordVersion() > originalVersion
                && !repository.markAvailable(
                    object.imageId(),
                    originalVersion,
                    object.objectVersion(),
                    object.width(),
                    object.height())) {
            StoredObject concurrent = repository.findById(object.imageId())
                .orElseThrow(() -> new DomainViolation("图片记录并发消失"));
            if (concurrent.state() != ObjectState.AVAILABLE) {
                throw new DomainViolation("图片确认发生并发冲突");
            }
        }
        if (session.status() == UploadSessionStatus.ISSUED
                && !sessions.markConfirmed(session.uploadSessionId(), now)) {
            throw new DomainViolation("上传会话确认发生并发冲突");
        }
        return repository.findById(object.imageId()).orElse(object);
    }

    @Transactional(readOnly = true)
    public URI issueRead(UUID imageId, String actorId, String purpose) {
        return issueReadAuthorization(imageId, actorId, purpose).url();
    }

    @Transactional(readOnly = true)
    public ReadAuthorization issueReadAuthorization(
            UUID imageId,
            String actorId,
            String purpose) {
        StoredObject object = repository.findById(imageId)
            .orElseThrow(() -> new DomainViolation("图片记录不存在"));
        object.requireAvailable();
        if (!"VIEW".equals(purpose) && !"DOWNLOAD".equals(purpose)) {
            throw new DomainViolation("读取用途不合法");
        }
        if (!authorizer.mayRead(actorId, imageId, purpose)) {
            throw new StorageAccessDenied("对象级访问被拒绝");
        }
        return new ReadAuthorization(
            storage.authorizeRead(
                object.bucket(),
                object.objectKey(),
                readTtl
            ),
            Instant.now(clock).plus(readTtl)
        );
    }

    public record ReadAuthorization(URI url, Instant expiresAt) {
        public ReadAuthorization {
            Objects.requireNonNull(url);
            Objects.requireNonNull(expiresAt);
        }
    }

    @Override
    @Transactional
    public void confirmDerived(DerivedObject object) {
        Objects.requireNonNull(object);
        if (!derivedBucket.equals(object.bucket())) {
            throw new StorageIntegrityViolation("派生对象桶不在批准范围");
        }
        if (!Set.of(
                "THUMBNAIL",
                "DEFECT_MASK",
                "HEATMAP",
                "OVERLAY",
                "POLAR"
            ).contains(object.kind())) {
            throw new StorageIntegrityViolation("派生对象类型不在批准范围");
        }
        if (object.sizeBytes() <= 0 || object.sizeBytes() > maximumObjectBytes
                || object.sha256() == null
                || !object.sha256().matches("[0-9a-f]{64}")
                || !object.objectKey().startsWith("derived/")) {
            throw new StorageIntegrityViolation("派生对象引用不合法");
        }
        ObjectStoragePort.ObjectHead head = storage.head(
            object.bucket(),
            object.objectKey()
        );
        long pixels;
        try {
            pixels = Math.multiplyExact((long) head.width(), (long) head.height());
        } catch (ArithmeticException error) {
            throw new StorageIntegrityViolation("派生对象解码尺寸溢出", error);
        }
        if (head.sizeBytes() != object.sizeBytes()
                || !head.sha256().equals(object.sha256())
                || !head.mediaType().equalsIgnoreCase(object.mediaType())
                || head.width() <= 0
                || head.height() <= 0
                || pixels > maximumPixels
                || head.decodedBytes() <= 0
                || head.decodedBytes() > maximumDecodedBytes) {
            throw new StorageIntegrityViolation(
                "派生对象大小、哈希、类型或解码尺寸不一致"
            );
        }
        repository.insertDerivedAvailable(
            object,
            head.objectVersion(),
            head.width(),
            head.height()
        );
    }

    private static Duration requireShortTtl(Duration value, String name) {
        if (value == null || value.isNegative() || value.isZero()
                || value.compareTo(Duration.ofMinutes(15)) > 0) {
            throw new DomainViolation(name + "授权必须为不超过 15 分钟的短时票据");
        }
        return value;
    }

    private void recordIntegrityFailure(
            StoredObject object,
            UploadSession session,
            String failureCode) {
        // 冻结错误码允许边缘端受控重传一次。第一次失败只关闭当前会话，
        // 对象仍保持不可被业务引用的 STAGING；再次失败才进入终态隔离。
        if (sessions.countFailed(object.imageId()) >= 1
                && !repository.markQuarantined(
                    object.imageId(),
                    object.recordVersion(),
                    failureCode)) {
            throw new DomainViolation("图片隔离发生并发冲突");
        }
        if (!sessions.markFailed(session.uploadSessionId(), failureCode)) {
            throw new DomainViolation("上传失败状态发生并发冲突");
        }
    }

    private static void requireBoundMetadata(
            Map<String, String> metadata,
            UploadSession session) {
        if (metadata == null
                || !session.receiptSha256().equals(metadata.get(META_RECEIPT_SHA256))
                || !session.expectedSha256().equals(metadata.get(META_CONTENT_SHA256))
                || !session.captureId().toString().equals(metadata.get(META_CAPTURE_ID))
                || !session.stationId().toString().equals(metadata.get(META_STATION_ID))) {
            throw new StorageIntegrityViolation("对象元数据未绑定上传会话");
        }
    }

    private static void requireSameStagingRegistration(
            StoredObject existing,
            StoredObject requested) {
        if (existing.state() != ObjectState.STAGING
                || !existing.captureId().equals(requested.captureId())
                || !existing.stationId().equals(requested.stationId())
                || !existing.bucket().equals(requested.bucket())
                || !existing.objectKey().equals(requested.objectKey())
                || existing.expectedSizeBytes() != requested.expectedSizeBytes()
                || !existing.expectedSha256().equals(requested.expectedSha256())
                || !existing.expectedMediaType().equals(requested.expectedMediaType())) {
            throw new DomainViolation("同一 imageId 的上传登记内容冲突");
        }
    }

    private static void requireEdgeMediaType(String mediaType, String extension) {
        if (!EDGE_MEDIA_TYPES.contains(mediaType)) {
            throw new DomainViolation("采集端媒体类型不在白名单");
        }
        String normalized = extension == null ? "" : extension.toLowerCase();
        boolean matches = switch (mediaType) {
            case "image/png" -> normalized.equals("png");
            case "image/jpeg" -> normalized.equals("jpg") || normalized.equals("jpeg");
            case "image/tiff" -> normalized.equals("tif") || normalized.equals("tiff");
            default -> false;
        };
        if (!matches) {
            throw new DomainViolation("扩展名与媒体类型不一致");
        }
    }

    private String newReceipt() {
        byte[] bytes = new byte[32];
        secureRandom.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(
                MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8))
            );
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("运行时缺少 SHA-256", impossible);
        }
    }

    private static String requireText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw new DomainViolation(name + "不能为空");
        }
        return value;
    }
}
