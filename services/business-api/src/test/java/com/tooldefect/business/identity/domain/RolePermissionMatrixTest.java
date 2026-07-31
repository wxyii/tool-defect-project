package com.tooldefect.business.identity.domain;

import static org.assertj.core.api.Assertions.assertThat;

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
    void administratorCannotSubmitQualityConclusionByDefault() {
        assertThat(RolePermissionMatrix.allows(
            SystemRole.SYSTEM_OPERATOR,
            "review:submit"
        )).isFalse();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.SYSTEM_OPERATOR,
            "quality:override"
        )).isFalse();
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
    void onlyQualityManagerCombinesReviewAndQualityApproval() {
        assertThat(RolePermissionMatrix.allows(
            SystemRole.QUALITY_MANAGER,
            "review:submit"
        )).isTrue();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.QUALITY_MANAGER,
            "dataset:approve"
        )).isTrue();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.REVIEWER,
            "dataset:approve"
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
        )).isTrue();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.OPERATOR,
            "quality:read"
        )).isFalse();
    }
}
