package com.tooldefect.business.detectionbatch.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
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

import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.shared.application.IdempotencyRepository;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.storage.application.ObjectStoragePort;

final class ManualDetectionBatchUploadRenewalTest {
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
    private static final Duration TTL = Duration.ofMinutes(10);
    private static final ManualDetectionSettings SETTINGS = new ManualDetectionSettings(
        true,
        BUCKET,
        "manual",
        10,
        10_000_000,
        List.of("image/jpeg", "image/png"),
        TTL,
        Duration.ofMinutes(5),
        Duration.ofHours(1),
        10
    );

    @Test
    void renewsTheExistingUploadingItemWithANewPresignedTicket() {
        var repository = mock(ManualDetectionRepository.class);
        var current = new ManualDetectionRepository.UploadIntent(
            UUID.fromString("019f0000-0000-7000-8000-000000000704"),
            item("UPLOADING"),
            ACTOR,
            "100.png",
            123L,
            "image/png",
            SHA256,
            NOW.plus(Duration.ofMinutes(1))
        );
        var renewed = new ManualDetectionRepository.UploadIntent(
            current.uploadId(),
            current.item(),
            current.ownerId(),
            current.fileName(),
            current.expectedSizeBytes(),
            current.expectedMediaType(),
            current.expectedSha256(),
            NOW.plus(TTL)
        );
        when(repository.findUpload(BATCH_ID, ITEM_ID, ACTOR))
            .thenReturn(Optional.of(current));
        when(repository.renewUpload(eq(BATCH_ID), eq(ITEM_ID), eq(ACTOR), any(Instant.class)))
            .thenReturn(renewed);
        var storage = mock(ObjectStoragePort.class);
        when(storage.authorizeUpload(
            eq(BUCKET),
            eq("manual/100.png"),
            eq(123L),
            eq(SHA256),
            eq("image/png"),
            anyMap(),
            eq(TTL)
        )).thenReturn(new ObjectStoragePort.UploadAuthorization(
            "PUT",
            URI.create("http://127.0.0.1:9000/td-raw/manual/100.png"),
            Map.of("content-type", "image/png"),
            NOW.plus(TTL),
            null
        ));

        var response = service(repository, storage).renewUpload(
            ACTOR,
            BATCH_ID,
            ITEM_ID,
            "renew-upload-key",
            Map.of(),
            "019f0000-0000-7000-8000-000000000705",
            "trace-renew"
        );

        assertThat(response.status()).isEqualTo(200);
        assertThat(response.body()).containsKey("upload");
        verify(repository).renewUpload(eq(BATCH_ID), eq(ITEM_ID), eq(ACTOR), any(Instant.class));
    }

    private static ManualDetectionBatchService service(
            ManualDetectionRepository repository, ObjectStoragePort storage) {
        var idempotencyRepository = mock(IdempotencyRepository.class);
        when(idempotencyRepository.find(anyString(), anyString(), anyString()))
            .thenReturn(Optional.empty());
        return new ManualDetectionBatchService(
            repository,
            storage,
            new IdempotencyService(idempotencyRepository),
            mock(AuditTrail.class),
            SETTINGS,
            Clock.fixed(NOW, ZoneOffset.UTC)
        );
    }

    private static ManualDetectionRepository.ItemView item(String status) {
        return new ManualDetectionRepository.ItemView(
            ITEM_ID,
            BATCH_ID,
            BUCKET,
            "manual/100.png",
            null,
            SHA256,
            123L,
            "image/png",
            status,
            null,
            null,
            NOW,
            NOW
        );
    }
}
