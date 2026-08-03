package com.tooldefect.business.detectionbatch.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

import java.time.Clock;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import jakarta.servlet.http.HttpServletRequest;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;

import com.tooldefect.business.detectionbatch.application.ManualDetectionBatchService;
import com.tooldefect.business.detectionbatch.application.ManualDetectionRepository;
import com.tooldefect.business.detectionbatch.application.ManualDetectionSettings;
import com.tooldefect.business.identity.application.LocalIdentity;
import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.IdempotencyRepository;
import com.tooldefect.business.storage.application.ObjectStoragePort;

final class ManualDetectionControllerTest {
    @Test
    void createAcceptsFrozenV2RequestWithoutOptionalUsageStageNote() {
        UUID userId = UUID.fromString(
            "019f0000-0000-7000-8000-000000000701"
        );
        var service = new RecordingService();
        var request = Map.<String, Object>of("usage_stage", "UNSPECIFIED");
        var identity = new LocalIdentity(
            userId,
            "operator",
            "生产员工",
            "ACTIVE",
            false,
            List.of("OPERATOR"),
            List.of("manual-detection:write")
        );
        var authentication = UsernamePasswordAuthenticationToken.authenticated(
            identity,
            "session-token",
            List.of()
        );

        var response = new ManualDetectionController(service).create(
            "create-without-note",
            request,
            authentication,
            mock(HttpServletRequest.class)
        );

        assertThat(response.getStatusCode().value()).isEqualTo(201);
        assertThat(service.actor).isEqualTo(userId);
        assertThat(service.key).isEqualTo("create-without-note");
        assertThat(service.stage).isEqualTo("UNSPECIFIED");
        assertThat(service.note).isNull();
        assertThat(service.request).isEqualTo(request);
    }

    private static final class RecordingService
            extends ManualDetectionBatchService {
        private UUID actor;
        private String key;
        private String stage;
        private String note;
        private Map<String, Object> request;

        private RecordingService() {
            super(
                mock(ManualDetectionRepository.class),
                mock(ObjectStoragePort.class),
                new IdempotencyService(mock(IdempotencyRepository.class)),
                mock(AuditTrail.class),
                new ManualDetectionSettings(
                    true,
                    "manual-originals",
                    "manual",
                    10,
                    10_000_000,
                    List.of("image/jpeg", "image/png"),
                    Duration.ofMinutes(10),
                    Duration.ofMinutes(5),
                    Duration.ofHours(1),
                    10
                ),
                Clock.systemUTC()
            );
        }

        @Override
        public IdempotencyService.Response create(
                UUID actor,
                String key,
                String stage,
                String note,
                Map<String, Object> request,
                String requestId,
                String traceId) {
            this.actor = actor;
            this.key = key;
            this.stage = stage;
            this.note = note;
            this.request = request;
            return new IdempotencyService.Response(
                201,
                Map.of("batch_id", UUID.randomUUID().toString())
            );
        }
    }
}
