package com.tooldefect.business.identity.domain;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Set;

import org.junit.jupiter.api.Test;

class RolePermissionMatrixTest {
    @Test
    void ordinaryOperatorCannotSubmitReviewOrDownloadOriginal() {
        assertThat(RolePermissionMatrix.allows(
            SystemRole.OPERATOR,
            "review:submit"
        )).isFalse();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.OPERATOR,
            "image:original:download"
        )).isFalse();
    }

    @Test
    void algorithmEngineerCannotChangeFinalDisposition() {
        assertThat(RolePermissionMatrix.allows(
            SystemRole.ALGORITHM_ENGINEER,
            "review:submit"
        )).isFalse();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.ALGORITHM_ENGINEER,
            "quality:override"
        )).isFalse();
    }

    @Test
    void systemAdministratorHasAllPersonnelPermissions() {
        Set<String> expected = Set.of(
            "capture:read",
            "detection:read",
            "image:view",
            "image:original:download",
            "review:read",
            "review:claim",
            "review:submit",
            "review:annotate",
            "review:escalate",
            "quality:override",
            "quality:read",
            "model:register",
            "model:validate",
            "model:approve",
            "model:deploy:approve",
            "model:rollback",
            "device:configure",
            "user:manage",
            "model:deploy:execute",
            "certificate:manage",
            "security:policy:manage",
            "audit:read"
        );

        assertThat(RolePermissionMatrix.permissions(SystemRole.SYSTEM_OPERATOR))
            .containsExactlyInAnyOrderElementsOf(expected);
    }

    @Test
    void auditorIsReadOnlyAndCannotDownloadOriginal() {
        assertThat(RolePermissionMatrix.allows(
            SystemRole.AUDITOR,
            "audit:read"
        )).isTrue();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.AUDITOR,
            "review:claim"
        )).isFalse();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.AUDITOR,
            "image:original:download"
        )).isFalse();
    }

    @Test
    void cancelledDatasetAndTrainingPermissionsAreNeverAssigned() {
        assertThat(RolePermissionMatrix.allows(
            SystemRole.QUALITY_MANAGER,
            "review:submit"
        )).isTrue();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.QUALITY_MANAGER,
            "dataset:approve"
        )).isFalse();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.SYSTEM_OPERATOR,
            "dataset:create"
        )).isFalse();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.ALGORITHM_ENGINEER,
            "training:create"
        )).isFalse();
    }

    @Test
    void qualityAndTrainingReadsFollowRoleBoundaries() {
        assertThat(RolePermissionMatrix.allows(
            SystemRole.QUALITY_MANAGER,
            "quality:read"
        )).isTrue();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.ALGORITHM_ENGINEER,
            "training:read"
        )).isFalse();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.OPERATOR,
            "quality:read"
        )).isFalse();
    }

    @Test
    void modelApprovalUsesDedicatedPermission() {
        assertThat(RolePermissionMatrix.allows(
            SystemRole.MODEL_APPROVER,
            "model:approve"
        )).isTrue();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.MODEL_APPROVER,
            "dataset:approve"
        )).isFalse();
    }
}
