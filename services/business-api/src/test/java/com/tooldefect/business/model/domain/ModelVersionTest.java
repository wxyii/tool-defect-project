package com.tooldefect.business.model.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import java.util.UUID;

import org.junit.jupiter.api.Test;

class ModelVersionTest {
    private static final Instant NOW = Instant.parse("2026-07-31T00:00:00Z");
    private static final UUID MODEL_ID = uuid(1);
    private static final UUID DATASET_ID = uuid(2);
    private static final UUID TRAINING_ID = uuid(3);
    private static final UUID REGISTRAR = uuid(4);
    private static final UUID VALIDATOR = uuid(5);
    private static final UUID RELEASE_APPROVER = uuid(6);

    @Test
    void completeSupplyChainRequiresIndependentValidationAndReleaseApproval() {
        var candidate = completeCandidate();

        var validated = candidate.withValidation(VALIDATOR, NOW);
        assertThat(validated.approvalState()).isEqualTo(ModelApprovalState.VALIDATED);
        assertThat(validated.validatedBy()).isEqualTo(VALIDATOR);

        var approved = validated.withFinalApproval(RELEASE_APPROVER, NOW.plusSeconds(1));
        assertThat(approved.approvalState()).isEqualTo(ModelApprovalState.APPROVED);
        assertThat(approved.approvedBy()).isEqualTo(RELEASE_APPROVER);
        assertThat(approved.hasCompleteSupplyChainEvidence()).isTrue();
    }

    @Test
    void registrarAndValidatorCannotApproveTheSameVersion() {
        var candidate = completeCandidate();

        assertThatThrownBy(() -> candidate.withValidation(REGISTRAR, NOW))
            .isInstanceOf(RuntimeException.class)
            .hasMessageContaining("登记人与验证审批人");

        var validated = candidate.withValidation(VALIDATOR, NOW);
        assertThatThrownBy(() -> validated.withFinalApproval(VALIDATOR, NOW.plusSeconds(1)))
            .isInstanceOf(RuntimeException.class)
            .hasMessageContaining("独立");
    }

    @Test
    void historicalVersionCanBeReadButCannotAdvanceWithoutSupplyChainEvidence() {
        var historical = new ModelVersion(
            uuid(10), MODEL_ID, 1, null, DATASET_ID,
            null, null, "models", "legacy/model.keras", "a".repeat(64),
            null, null, "{}", "{}", "{}", null, null,
            ModelApprovalState.CANDIDATE, null, null, null, null, null, NOW
        );

        assertThat(historical.hasCompleteSupplyChainEvidence()).isFalse();
        assertThatThrownBy(() -> historical.withValidation(VALIDATOR, NOW))
            .isInstanceOf(RuntimeException.class)
            .hasMessageContaining("只能 HOLD");
    }

    private static ModelVersion completeCandidate() {
        return new ModelVersion(
            uuid(20), MODEL_ID, 1, TRAINING_ID, DATASET_ID,
            "registry", "1", "models", "model-1.keras", "a".repeat(64),
            "b".repeat(64), "key-1", "{}", "{}", "{}",
            "c".repeat(64), "d".repeat(64), ModelApprovalState.CANDIDATE,
            REGISTRAR, null, null, null, null, NOW
        );
    }

    private static UUID uuid(int value) {
        return UUID.fromString("00000000-0000-0000-0000-0000000000" + value);
    }
}
