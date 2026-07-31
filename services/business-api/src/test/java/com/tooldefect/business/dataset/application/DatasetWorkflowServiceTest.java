package com.tooldefect.business.dataset.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import com.tooldefect.business.dataset.domain.CandidateManifest;
import com.tooldefect.business.dataset.domain.DatasetVersion;
import com.tooldefect.business.shared.application.IdempotencyRepository;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.Uuid7Generator;
import com.tooldefect.business.shared.domain.DomainViolation;

class DatasetWorkflowServiceTest {
    private static final Instant NOW = Instant.parse("2026-07-31T12:00:00Z");
    private static final UUID DATASET_ID = UUID.fromString(
        "019fb1b0-0000-7000-8000-000000000001"
    );
    private static final UUID CANDIDATE_ID = UUID.fromString(
        "019fb1b0-0000-7000-8000-000000000002"
    );
    private static final UUID APPROVER_ID = UUID.fromString(
        "019fb1b0-0000-7000-8000-000000000003"
    );
    private static final UUID REQUESTER_ID = UUID.fromString(
        "019fb1b0-0000-7000-8000-000000000004"
    );

    private DatasetRepository repository;
    private DatasetWorkflowService service;

    @BeforeEach
    void setUp() {
        repository = mock(DatasetRepository.class);
        IdempotencyRepository idempotencyRepository = mock(IdempotencyRepository.class);
        when(idempotencyRepository.find(anyString(), anyString(), anyString()))
            .thenReturn(Optional.empty());
        Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
        service = new DatasetWorkflowService(
            repository,
            new IdempotencyService(idempotencyRepository),
            new Uuid7Generator(clock, new SecureRandom(new byte[] { 7, 3, 1 })),
            clock
        );
    }

    @Test
    void createsOnlyFromApprovedCandidateAndReturnsFrozenAsyncShape() {
        when(repository.findCandidateManifest(CANDIDATE_ID))
            .thenReturn(Optional.of(candidate(CandidateManifest.ApprovalState.APPROVED)));
        when(repository.findLatestVersion(DATASET_ID)).thenReturn(Optional.empty());

        var response = service.createVersion(
            REQUESTER_ID.toString(),
            "dataset-create-key",
            Map.of(
                "dataset_id", DATASET_ID.toString(),
                "candidate_manifest_id", CANDIDATE_ID.toString(),
                "purpose", "P6 生产候选数据集"
            )
        );

        assertThat(response.status()).isEqualTo(202);
        assertThat(response.body())
            .containsEntry("status", "QUEUED")
            .containsEntry("poll_after_ms", 1000)
            .containsKey("job_id");
        ArgumentCaptor<DatasetVersion> captured = ArgumentCaptor.forClass(DatasetVersion.class);
        verify(repository).insertVersion(captured.capture());
        assertThat(captured.getValue().version()).isEqualTo("1");
        assertThat(captured.getValue().state().name()).isEqualTo("BUILDING");
        assertThat(captured.getValue().candidateManifestId()).isEqualTo(CANDIDATE_ID);
        assertThat(captured.getValue().purpose()).isEqualTo("P6 生产候选数据集");
    }

    @Test
    void rejectsUnapprovedCandidateWithoutCreatingVersion() {
        when(repository.findCandidateManifest(CANDIDATE_ID))
            .thenReturn(Optional.of(candidate(CandidateManifest.ApprovalState.REGISTERED)));

        assertThatThrownBy(() -> service.createVersion(
            REQUESTER_ID.toString(),
            "dataset-create-key",
            Map.of(
                "dataset_id", DATASET_ID.toString(),
                "candidate_manifest_id", CANDIDATE_ID.toString(),
                "purpose", "P6 生产候选数据集"
            )
        )).isInstanceOf(DomainViolation.class)
            .hasMessageContaining("独立质量审批");
    }

    private static CandidateManifest candidate(CandidateManifest.ApprovalState state) {
        return new CandidateManifest(
            CANDIDATE_ID,
            DATASET_ID,
            "td-datasets",
            "candidate/production-candidate-v1/manifest.csv",
            "a".repeat(64),
            172,
            state,
            state == CandidateManifest.ApprovalState.APPROVED ? APPROVER_ID : null,
            state == CandidateManifest.ApprovalState.APPROVED ? NOW : null,
            NOW.minusSeconds(60)
        );
    }
}
