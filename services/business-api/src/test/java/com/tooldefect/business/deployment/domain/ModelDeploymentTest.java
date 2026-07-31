package com.tooldefect.business.deployment.domain;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import java.util.UUID;

import org.junit.jupiter.api.Test;

class ModelDeploymentTest {
    private static final Instant NOW = Instant.parse("2026-07-31T00:00:00Z");
    private static final UUID MODEL_VERSION = uuid(1);
    private static final UUID ROLLBACK_VERSION = uuid(2);
    private static final UUID REQUESTER = uuid(3);
    private static final UUID QUALITY = uuid(4);
    private static final UUID RELEASE = uuid(5);

    @Test
    void deploymentNeedsTwoIndependentApprovalsBeforeActivationAndRollback() {
        var requested = deployment();
        var qualityApproved = requested.withApproval(
            DeploymentApprovalRole.QUALITY_APPROVER, QUALITY, NOW);
        assertThat(qualityApproved.status()).isEqualTo(DeploymentStatus.REQUESTED);

        var approved = qualityApproved.withApproval(
            DeploymentApprovalRole.MODEL_RELEASE_APPROVER, RELEASE, NOW.plusSeconds(1));
        assertThat(approved.status()).isEqualTo(DeploymentStatus.APPROVED);
        assertThat(approved.recordVersion()).isEqualTo(2);

        var active = approved.withActivation("a".repeat(64), "b".repeat(64));
        assertThat(active.warmupEvidenceSha256()).hasSize(64);
        var rolledBack = active.withRollback(ROLLBACK_VERSION, "c".repeat(64));
        assertThat(rolledBack.status()).isEqualTo(DeploymentStatus.ROLLED_BACK);
    }

    @Test
    void requesterAndApproversMustBeDifferent() {
        assertThatThrownBy(() -> deployment().withApproval(
            DeploymentApprovalRole.QUALITY_APPROVER, REQUESTER, NOW))
            .isInstanceOf(RuntimeException.class)
            .hasMessageContaining("请求人与审批人");

        var qualityApproved = deployment().withApproval(
            DeploymentApprovalRole.QUALITY_APPROVER, QUALITY, NOW);
        assertThatThrownBy(() -> qualityApproved.withApproval(
            DeploymentApprovalRole.MODEL_RELEASE_APPROVER, QUALITY, NOW.plusSeconds(1)))
            .isInstanceOf(RuntimeException.class)
            .hasMessageContaining("独立");
    }

    @Test
    void historicalDeploymentCanBeReadButCannotAdvance() {
        var historical = new ModelDeployment(
            uuid(10), MODEL_VERSION, DeploymentEnvironment.PRODUCTION,
            DeploymentStrategy.PERCENTAGE, "[]", 0.0, null, null,
            null, null, null, null, null, null, null, DeploymentStatus.REQUESTED, NOW, 0
        );

        assertThat(historical.hasCompleteReleaseContext()).isFalse();
        assertThatThrownBy(() -> historical.withApproval(
            DeploymentApprovalRole.QUALITY_APPROVER, QUALITY, NOW))
            .isInstanceOf(RuntimeException.class)
            .hasMessageContaining("只能 HOLD");
    }

    @Test
    void shadowDeploymentCannotCarryProductionTraffic() {
        assertThatThrownBy(() -> new ModelDeployment(
            uuid(11), MODEL_VERSION, DeploymentEnvironment.SHADOW,
            DeploymentStrategy.PERCENTAGE, "[]", 0.1, REQUESTER, ROLLBACK_VERSION,
            null, null, null, null, null, null, null, DeploymentStatus.REQUESTED, NOW, 0
        )).isInstanceOf(RuntimeException.class)
            .hasMessageContaining("影子环境");
    }

    @Test
    void approvedDeploymentCannotActivateWithoutRuntimeEvidence() {
        var approved = deployment()
            .withApproval(DeploymentApprovalRole.QUALITY_APPROVER, QUALITY, NOW)
            .withApproval(DeploymentApprovalRole.MODEL_RELEASE_APPROVER, RELEASE, NOW.plusSeconds(1));

        assertThatThrownBy(() -> approved.withStatus(DeploymentStatus.ACTIVE))
            .isInstanceOf(RuntimeException.class)
            .hasMessageContaining("运行时");
    }

    @Test
    void activeDeploymentCannotRollbackWithoutRuntimeEvidence() {
        var active = deployment()
            .withApproval(DeploymentApprovalRole.QUALITY_APPROVER, QUALITY, NOW)
            .withApproval(DeploymentApprovalRole.MODEL_RELEASE_APPROVER, RELEASE, NOW.plusSeconds(1))
            .withActivation("a".repeat(64), "b".repeat(64));

        assertThatThrownBy(() -> active.withRollback(ROLLBACK_VERSION, null))
            .isInstanceOf(RuntimeException.class)
            .hasMessageContaining("回滚运行证据");
        assertThatThrownBy(() -> active.withStatus(DeploymentStatus.ROLLED_BACK))
            .isInstanceOf(RuntimeException.class)
            .hasMessageContaining("运行证据");
    }

    private static ModelDeployment deployment() {
        return new ModelDeployment(
            uuid(20), MODEL_VERSION, DeploymentEnvironment.CANARY,
            DeploymentStrategy.PERCENTAGE, "[]", 0.1, REQUESTER, ROLLBACK_VERSION,
            null, null, null, null, null, null, null, DeploymentStatus.REQUESTED, NOW, 0
        );
    }

    private static UUID uuid(int value) {
        return UUID.fromString("00000000-0000-0000-0000-0000000000" + value);
    }
}
