package com.tooldefect.business.storage.application;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URI;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.storage.domain.ObjectState;
import com.tooldefect.business.storage.domain.StorageIntegrityViolation;
import com.tooldefect.business.storage.domain.StoredObject;
import com.tooldefect.business.storage.domain.UploadSession;
import com.tooldefect.business.storage.domain.UploadSessionStatus;

final class StorageApplicationServiceTest {
    private static final UUID CAPTURE = uuid(2);
    private static final UUID STATION = uuid(3);
    private static final UUID REVIEW_TASK = uuid(4);
    private static final UUID REVIEW_IMAGE = uuid(5);
    private static final String SHA256 = "a".repeat(64);

    private MutableClock clock;
    private MemoryObjects objects;
    private MemorySessions sessions;
    private FakeStorage storage;
    private StorageApplicationService service;

    @BeforeEach
    void setUp() {
        clock = new MutableClock(Instant.parse("2026-07-29T01:00:00Z"));
        objects = new MemoryObjects();
        objects.bindReview(REVIEW_TASK, CAPTURE, STATION, 10, 10);
        sessions = new MemorySessions();
        storage = new FakeStorage(clock);
        service = new StorageApplicationService(
            objects,
            sessions,
            storage,
            new StationScopeAuthorizer() {
                @Override
                public boolean mayWrite(UUID actor, UUID objectStation) {
                    return actor.equals(objectStation);
                }

                @Override
                public boolean mayRead(String actorId, UUID imageId, String purpose) {
                    return "operator".equals(actorId) && "VIEW".equals(purpose);
                }
            },
            new ObjectKeyPolicy(),
            clock,
            new SecureRandom(new byte[] {1, 2, 3, 4}),
            "td-raw",
            "td-derived",
            "td-review",
            Duration.ofMinutes(5),
            Duration.ofMinutes(2),
            1_000,
            10_000,
            40_000
        );
    }

    @Test
    void reviewMaskMustMatchTheAvailableOriginalDimensions() {
        assertThrows(StorageIntegrityViolation.class, () -> service.issue(
            REVIEW_IMAGE,
            REVIEW_TASK,
            CAPTURE,
            10,
            SHA256,
            9,
            10
        ));
        assertTrue(objects.findById(REVIEW_IMAGE).isEmpty());
    }

    @Test
    void reviewMaskRejectsMultipleChannelsAndNonBinaryValues() {
        var ticket = issueReview(REVIEW_IMAGE);
        storage.bands = 3;

        assertThrows(StorageIntegrityViolation.class, () -> service.confirm(
            REVIEW_TASK,
            REVIEW_IMAGE,
            10,
            SHA256,
            receipt(ticket)
        ));
        assertEquals(
            ObjectState.STAGING,
            objects.findById(REVIEW_IMAGE).orElseThrow().state()
        );

        UUID secondImage = uuid(6);
        storage.bands = 1;
        storage.binaryMask = false;
        var secondTicket = issueReview(secondImage);
        assertThrows(StorageIntegrityViolation.class, () -> service.confirm(
            REVIEW_TASK,
            secondImage,
            10,
            SHA256,
            receipt(secondTicket)
        ));
    }

    @Test
    void confirmedUnsubmittedReviewMaskRemainsLinkedForOrphanReconciliation() {
        var ticket = issueReview(REVIEW_IMAGE);

        var confirmed = service.confirm(
            REVIEW_TASK,
            REVIEW_IMAGE,
            10,
            SHA256,
            receipt(ticket)
        );

        assertEquals(REVIEW_IMAGE, confirmed.imageId());
        assertEquals(SHA256, confirmed.sha256());
        assertEquals(
            ObjectState.AVAILABLE,
            objects.findById(REVIEW_IMAGE).orElseThrow().state()
        );
        assertEquals(
            REVIEW_TASK,
            objects.reviewMaskExpectation(REVIEW_IMAGE)
                .orElseThrow()
                .reviewTaskId()
        );
        assertThrows(DomainViolation.class, () ->
            issueReview(REVIEW_IMAGE)
        );
    }

    @Test
    void damagedReviewMaskFailsClosed() {
        var ticket = issueReview(REVIEW_IMAGE);
        storage.missing = true;

        assertThrows(StorageIntegrityViolation.class, () -> service.confirm(
            REVIEW_TASK,
            REVIEW_IMAGE,
            10,
            SHA256,
            receipt(ticket)
        ));
        assertEquals(
            ObjectState.STAGING,
            objects.findById(REVIEW_IMAGE).orElseThrow().state()
        );
    }

    private ReviewAnnotationStorage.UploadTicket issueReview(UUID imageId) {
        return service.issue(
            imageId,
            REVIEW_TASK,
            CAPTURE,
            10,
            SHA256,
            10,
            10
        );
    }

    private static String receipt(
            ReviewAnnotationStorage.UploadTicket ticket) {
        return ticket.headers().get(
            StorageApplicationService.UPLOAD_RECEIPT_HEADER
        );
    }

    private static UUID uuid(long value) {
        return new UUID(0x0000000000007000L, 0x8000000000000000L | value);
    }

    private static StoredObject copy(StoredObject value) {
        return StoredObject.restore(
            value.imageId(),
            value.captureId(),
            value.stationId(),
            value.bucket(),
            value.objectKey(),
            value.expectedSizeBytes(),
            value.expectedSha256(),
            value.expectedMediaType(),
            value.state(),
            value.objectVersion(),
            value.width(),
            value.height(),
            value.recordVersion()
        );
    }

    private static final class MemoryObjects implements StoredObjectRepository {
        private final Map<UUID, StoredObject> values = new HashMap<>();
        private final Map<UUID, ReviewSourceBinding> reviewSources =
            new HashMap<>();
        private final Map<UUID, ReviewMaskExpectation> reviewMasks =
            new HashMap<>();

        void bindReview(
                UUID reviewTaskId,
                UUID captureId,
                UUID stationId,
                int width,
                int height) {
            reviewSources.put(
                reviewTaskId,
                new ReviewSourceBinding(
                    captureId,
                    new ReviewMaskSource(stationId, width, height)
                )
            );
        }

        @Override
        public Optional<StoredObject> findById(UUID imageId) {
            return Optional.ofNullable(values.get(imageId)).map(StorageApplicationServiceTest::copy);
        }

        @Override
        public Optional<StoredObject> findByIdForUpdate(UUID imageId) {
            return findById(imageId);
        }

        @Override
        public void insertStaging(StoredObject object) {
            if (values.putIfAbsent(object.imageId(), copy(object)) != null) {
                throw new DomainViolation("重复图片");
            }
        }

        @Override
        public void insertReviewMaskStaging(
                StoredObject object,
                UUID reviewTaskId,
                int expectedWidth,
                int expectedHeight) {
            insertStaging(object);
            reviewMasks.put(
                object.imageId(),
                new ReviewMaskExpectation(
                    reviewTaskId,
                    expectedWidth,
                    expectedHeight
                )
            );
        }

        @Override
        public Optional<ReviewMaskSource> reviewMaskSource(
                UUID reviewTaskId,
                UUID captureId) {
            ReviewSourceBinding binding = reviewSources.get(reviewTaskId);
            if (binding == null || !binding.captureId().equals(captureId)) {
                return Optional.empty();
            }
            return Optional.of(binding.source());
        }

        @Override
        public Optional<ReviewMaskExpectation> reviewMaskExpectation(
                UUID imageId) {
            return Optional.ofNullable(reviewMasks.get(imageId));
        }

        private record ReviewSourceBinding(
            UUID captureId,
            ReviewMaskSource source
        ) {
        }

        @Override
        public boolean markAvailable(
                UUID imageId,
                long expectedRecordVersion,
                String objectVersion,
                int width,
                int height) {
            StoredObject current = values.get(imageId);
            if (current == null || current.recordVersion() != expectedRecordVersion) {
                return false;
            }
            current.confirm(
                current.expectedSizeBytes(),
                current.expectedSha256(),
                current.expectedMediaType(),
                width,
                height,
                objectVersion
            );
            return true;
        }

        @Override
        public boolean markQuarantined(
                UUID imageId,
                long expectedRecordVersion,
                String reason) {
            StoredObject current = values.get(imageId);
            if (current == null || current.recordVersion() != expectedRecordVersion) {
                return false;
            }
            current.quarantine();
            return true;
        }
    }

    private static final class MemorySessions implements UploadSessionRepository {
        private final List<UploadSession> values = new ArrayList<>();

        UploadSession latest() {
            return values.getLast();
        }

        @Override
        public Optional<UploadSession> findLatest(UUID imageId) {
            return values.reversed().stream()
                .filter(value -> value.imageId().equals(imageId))
                .findFirst();
        }

        @Override
        public Optional<UploadSession> findLatestForUpdate(UUID imageId) {
            return findLatest(imageId);
        }

        @Override
        public long countFailed(UUID imageId) {
            return values.stream()
                .filter(value -> value.imageId().equals(imageId))
                .filter(value -> value.status() == UploadSessionStatus.FAILED)
                .count();
        }

        @Override
        public void revokeIssued(UUID imageId, String reason) {
            for (int index = 0; index < values.size(); index++) {
                UploadSession value = values.get(index);
                if (value.imageId().equals(imageId)
                        && value.status() == UploadSessionStatus.ISSUED) {
                    values.set(index, withStatus(value, UploadSessionStatus.REVOKED));
                }
            }
        }

        @Override
        public void insert(UploadSession session) {
            values.add(session);
        }

        @Override
        public boolean markConfirmed(UUID uploadSessionId, Instant confirmedAt) {
            return replace(uploadSessionId, UploadSessionStatus.CONFIRMED);
        }

        @Override
        public boolean markExpired(UUID uploadSessionId) {
            return replace(uploadSessionId, UploadSessionStatus.EXPIRED);
        }

        @Override
        public boolean markFailed(UUID uploadSessionId, String failureCode) {
            return replace(uploadSessionId, UploadSessionStatus.FAILED);
        }

        private boolean replace(UUID id, UploadSessionStatus status) {
            for (int index = 0; index < values.size(); index++) {
                if (values.get(index).uploadSessionId().equals(id)) {
                    values.set(index, withStatus(values.get(index), status));
                    return true;
                }
            }
            return false;
        }

        private static UploadSession withStatus(
                UploadSession value,
                UploadSessionStatus status) {
            return new UploadSession(
                value.uploadSessionId(),
                value.imageId(),
                value.captureId(),
                value.stationId(),
                value.receiptSha256(),
                value.expectedSizeBytes(),
                value.expectedSha256(),
                value.expectedMediaType(),
                status,
                value.expiresAt()
            );
        }
    }

    private static final class FakeStorage implements ObjectStoragePort {
        private final Clock clock;
        private Map<String, String> metadata = Map.of();
        private boolean missing;
        private long decodedBytes = 400;
        private int width = 10;
        private int height = 10;
        private int bands = 1;
        private boolean binaryMask = true;

        FakeStorage(Clock clock) {
            this.clock = clock;
        }

        @Override
        public UploadAuthorization authorizeUpload(
                String bucket,
                String objectKey,
                long sizeBytes,
                String sha256,
                String mediaType,
                Map<String, String> objectMetadata,
                Duration ttl) {
            metadata = Map.copyOf(objectMetadata);
            return new UploadAuthorization(
                "PUT",
                URI.create("https://storage.invalid/upload"),
                Map.of("content-type", mediaType),
                Instant.now(clock).plus(ttl),
                null
            );
        }

        @Override
        public ObjectHead head(String bucket, String objectKey) {
            if (missing) {
                throw new StorageIntegrityViolation("对象不存在");
            }
            return new ObjectHead(
                10,
                SHA256,
                "image/png",
                width,
                height,
                decodedBytes,
                bands,
                binaryMask,
                "version-1",
                metadata
            );
        }

        @Override
        public URI authorizeRead(String bucket, String objectKey, Duration ttl) {
            return URI.create("https://storage.invalid/read");
        }

        @Override
        public void delete(String bucket, String objectKey) {
        }
    }

    private static final class MutableClock extends Clock {
        private Instant value;

        MutableClock(Instant value) {
            this.value = value;
        }

        void advance(Duration duration) {
            value = value.plus(duration);
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return value;
        }
    }
}
