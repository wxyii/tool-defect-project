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
import com.tooldefect.business.dataset.domain.DatasetVersionState;
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
    void createsDiscoverableDatasetRootWithServerGeneratedIdentifier() {
        var response = service.createDataset(
            REQUESTER_ID.toString(),
            "dataset-catalog-key",
            Map.of(
                "dataset_name", "生产候选集",
                "purpose", "增量训练"
            )
        );

        assertThat(response.status()).isEqualTo(201);
        assertThat(response.body())
            .containsEntry("dataset_name", "生产候选集")
            .containsEntry("purpose", "增量训练")
            .containsEntry("version_count", 0)
            .containsEntry("created_at", NOW.toString());
        assertThat(response.body().get("dataset_id").toString())
            .matches("[0-9a-f-]{36}");
        verify(repository).insertDataset(
            any(UUID.class),
            eq("生产候选集"),
            eq("增量训练"),
            eq(NOW)
        );
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

    @Test
    void approvesRegisteredCandidateManifestWithStableContractShape() {
        CandidateManifest registered = candidate(
            CandidateManifest.ApprovalState.REGISTERED
        );
        when(repository.findCandidateManifest(CANDIDATE_ID))
            .thenReturn(Optional.of(registered));

        var response = service.approveCandidateManifest(
            APPROVER_ID.toString(),
            "candidate-approval-key",
            CANDIDATE_ID,
            Map.of("decision", "APPROVE")
        );

        assertThat(response.status()).isEqualTo(200);
        assertThat(response.body())
            .containsEntry("candidate_manifest_id", CANDIDATE_ID.toString())
            .containsEntry("approval_state", "APPROVED")
            .containsEntry("approved_by", APPROVER_ID.toString())
            .containsEntry("approved_at", NOW.toString())
            .containsEntry("message", "候选清单已批准");
        ArgumentCaptor<CandidateManifest> captured = ArgumentCaptor.forClass(
            CandidateManifest.class
        );
        verify(repository).updateCandidateManifest(captured.capture());
        assertThat(captured.getValue().approvalState())
            .isEqualTo(CandidateManifest.ApprovalState.APPROVED);
    }

    @Test
    void freezesValidatedDatasetVersionWithStableContractShape() {
        DatasetVersion validating = new DatasetVersion(
            UUID.fromString("019fb1b0-0000-7000-8000-000000000005"),
            DATASET_ID,
            "1",
            null,
            CANDIDATE_ID,
            "受控增量训练",
            "candidate/production-candidate-v1/manifest.csv",
            "td-datasets",
            "a".repeat(64),
            172,
            "{}",
            DatasetVersionState.VALIDATING,
            null,
            NOW.minusSeconds(30),
            null,
            1
        );
        when(repository.findVersion(validating.datasetVersionId()))
            .thenReturn(Optional.of(validating));

        var response = service.approveVersion(
            APPROVER_ID.toString(),
            "version-approval-key",
            validating.datasetVersionId(),
            Map.of("decision", "APPROVE")
        );

        assertThat(response.status()).isEqualTo(200);
        assertThat(response.body())
            .containsEntry(
                "dataset_version_id",
                validating.datasetVersionId().toString()
            )
            .containsEntry("version", "1")
            .containsEntry("state", "FROZEN")
            .containsEntry("approved_at", NOW.toString())
            .containsEntry("message", "数据集版本已冻结");
        ArgumentCaptor<DatasetVersion> captured = ArgumentCaptor.forClass(
            DatasetVersion.class
        );
        verify(repository).updateVersion(captured.capture());
        assertThat(captured.getValue().state())
            .isEqualTo(DatasetVersionState.FROZEN);
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
