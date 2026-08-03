package com.tooldefect.business.identity.domain;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Set;

import org.junit.jupiter.api.Test;

class RolePermissionMatrixTest {
    @Test
    void onlyTwoPersonRolesAreExposed() {
        assertThat(SystemRole.values())
            .containsExactly(SystemRole.PRODUCTION_EMPLOYEE, SystemRole.ADMINISTRATOR);
    }

    @Test
    void productionEmployeeIsLimitedToProductionAndManualDetection() {
        Set<String> permissions = RolePermissionMatrix.permissions(
            SystemRole.PRODUCTION_EMPLOYEE);

        assertThat(permissions).containsExactlyInAnyOrder(
            "capture:read",
            "detection:read",
            "image:view",
            "manual-detection:read",
            "manual-detection:write"
        );
        assertThat(permissions).doesNotContain(
            "user:manage",
            "model:approve",
            "dataset:create",
            "dataset:approve",
            "training:create",
            "training:read"
        );
    }

    @Test
    void administratorHasModelApprovalButNoDatasetOrTrainingPermission() {
        Set<String> permissions = RolePermissionMatrix.permissions(
            SystemRole.ADMINISTRATOR);

        assertThat(permissions).contains(
            "user:manage",
            "model:register",
            "model:validate",
            "model:approve",
            "model:deploy:approve",
            "model:deploy:execute",
            "audit:read"
        );
        assertThat(permissions).doesNotContain(
            "dataset:create",
            "dataset:approve",
            "training:create",
            "training:read"
        );
    }

    @Test
    void administratorCanReviewButCannotBypassResourceRules() {
        assertThat(RolePermissionMatrix.allows(
            SystemRole.ADMINISTRATOR,
            "review:submit"
        )).isTrue();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.ADMINISTRATOR,
            "quality:override"
        )).isTrue();
        assertThat(RolePermissionMatrix.allows(
            SystemRole.PRODUCTION_EMPLOYEE,
            "review:submit"
        )).isFalse();
    }
}
