package com.tooldefect.business.detectionbatch.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.net.URI;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.audit.domain.AuditRecord;
import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.application.IdempotencyRepository;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.storage.application.ObjectStoragePort;

final class ManualDetectionBatchServiceTest {
    private static final UUID ACTOR = UUID.fromString(
        "019f0000-0000-7000-8000-000000000701"
    );
    private static final UUID BATCH_ID = UUID.fromString(
        "019f0000-0000-7000-8000-000000000702"
    );
    private static final UUID ITEM_ID = UUID.fromString(
        "019f0000-0000-7000-8000-000000000703"
    );
    private static final Instant NOW = Instant.parse("2026-08-03T07:00:00Z");
    private static final String SHA256 = "a".repeat(64);
    private static final String BUCKET = "manual-originals";
    private static final Clock CLOCK = Clock.fixed(NOW, ZoneOffset.UTC);
    private static final ManualDetectionSettings SETTINGS = new ManualDetectionSettings(
        true,
        BUCKET,
        "manual",
        10,
        10_000_000,
        List.of("image/jpeg", "image/png"),
        Duration.ofMinutes(10),
        Duration.ofMinutes(5),
        Duration.ofHours(1),
        10
    );

    @Test
    void createUsesJsonCompatibleBatchSnapshotForAuditDigest() {
        var repository = mock(ManualDetectionRepository.class);
        when(repository.createBatch(ACTOR, "UNSPECIFIED", null)).thenReturn(batch());
        var audit = mock(AuditTrail.class);

        var response = service(repository, mock(ObjectStoragePort.class), audit).create(
            ACTOR,
            "create-batch-key",
            "UNSPECIFIED",
            null,
            Map.of("usage_stage", "UNSPECIFIED"),
            "019f0000-0000-7000-8000-000000000704",
            "trace-create"
        );

        assertThat(response.status()).isEqualTo(201);
        assertThat(response.body()).containsEntry("batch_id", BATCH_ID.toString());
        assertThat(CanonicalJson.encode(response.body())).isNotBlank();
        assertAuditDigest(audit);
    }

    @Test
    void addItemUsesJsonCompatibleItemSnapshotForAuditDigest() {
        var repository = mock(ManualDetectionRepository.class);
        var item = item();
        var intent = new ManualDetectionRepository.UploadIntent(
            UUID.fromString("019f0000-0000-7000-8000-000000000705"),
            item,
            ACTOR,
            "100.png",
            123L,
            "image/png",
            SHA256,
            NOW.plus(Duration.ofMinutes(10))
        );
        when(repository.addItem(
            eq(BATCH_ID),
            any(UUID.class),
            eq(ACTOR),
            eq("100.png"),
            eq(123L),
            eq("image/png"),
            eq(SHA256),
            eq(BUCKET),
            anyString(),
            any(Instant.class),
            eq(10)
        )).thenReturn(intent);
        var storage = mock(ObjectStoragePort.class);
        when(storage.authorizeUpload(
            anyString(),
            anyString(),
            eq(123L),
            eq(SHA256),
            eq("image/png"),
            anyMap(),
            any(Duration.class)
        )).thenReturn(new ObjectStoragePort.UploadAuthorization(
            "PUT",
            URI.create("https://storage.example.invalid/upload"),
            Map.of("Content-Type", "image/png"),
            NOW.plus(Duration.ofMinutes(10)),
            "receipt"
        ));
        var audit = mock(AuditTrail.class);

        var response = service(repository, storage, audit).addItem(
            ACTOR,
            BATCH_ID,
            "add-item-key",
            "100.png",
            123L,
            "image/png",
            SHA256,
            Map.of("file_name", "100.png"),
            "019f0000-0000-7000-8000-000000000706",
            "trace-add"
        );

        assertThat(response.status()).isEqualTo(201);
        assertThat(response.body()).containsKey("upload");
        assertThat(CanonicalJson.encode(response.body())).isNotBlank();
        assertAuditDigest(audit);
    }

    @Test
    void quickReviewUsesJsonCompatibleSnapshotForAuditDigest() {
        var repository = mock(ManualDetectionRepository.class);
        when(repository.saveQuickReview(
            eq(BATCH_ID),
            eq(ITEM_ID),
            eq(ACTOR),
            eq(false),
            eq("DEFECT_CONFIRMED"),
            isNull(),
            eq("quick-review-key")
        )).thenReturn(new ManualDetectionRepository.QuickReviewView(
            UUID.fromString("019f0000-0000-7000-8000-000000000707"),
            ITEM_ID,
            "DEFECT_CONFIRMED",
            ACTOR,
            NOW,
            "quick-review-key",
            null
        ));
        var audit = mock(AuditTrail.class);

        var response = service(repository, mock(ObjectStoragePort.class), audit)
            .saveQuickReview(
                ACTOR,
                false,
                BATCH_ID,
                ITEM_ID,
                "quick-review-key",
                "DEFECT_CONFIRMED",
                null,
                Map.of("decision", "DEFECT_CONFIRMED"),
                "019f0000-0000-7000-8000-000000000708",
                "trace-review"
            );

        assertThat(response.status()).isEqualTo(200);
        assertThat(response.body()).containsEntry("decision", "DEFECT_CONFIRMED");
        assertThat(CanonicalJson.encode(response.body())).isNotBlank();
        assertAuditDigest(audit);
    }

    private static ManualDetectionBatchService service(
            ManualDetectionRepository repository,
            ObjectStoragePort storage,
            AuditTrail audit) {
        var idempotencyRepository = mock(IdempotencyRepository.class);
        when(idempotencyRepository.find(anyString(), anyString(), anyString()))
            .thenReturn(Optional.empty());
        return new ManualDetectionBatchService(
            repository,
            storage,
            new IdempotencyService(idempotencyRepository),
            audit,
            SETTINGS,
            CLOCK
        );
    }

    private static ManualDetectionRepository.BatchView batch() {
        return new ManualDetectionRepository.BatchView(
            BATCH_ID,
            "B-0001",
            ACTOR,
            "UNSPECIFIED",
            null,
            "DRAFT",
            new ManualDetectionRepository.Counts(0, 0, 0, 0, 0, 0, 0),
            NOW,
            NOW,
            1L
        );
    }

    private static ManualDetectionRepository.ItemView item() {
        return new ManualDetectionRepository.ItemView(
            ITEM_ID,
            BATCH_ID,
            BUCKET,
            "manual/100.png",
            null,
            SHA256,
            123L,
            "image/png",
            "READY",
            null,
            null,
            NOW,
            NOW
        );
    }

    private static void assertAuditDigest(AuditTrail audit) {
        var captor = ArgumentCaptor.forClass(AuditRecord.class);
        verify(audit).append(captor.capture());
        assertThat(captor.getValue().afterDigest()).matches("[0-9a-f]{64}");
    }
}
