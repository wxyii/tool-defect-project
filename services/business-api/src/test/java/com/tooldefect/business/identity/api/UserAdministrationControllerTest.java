package com.tooldefect.business.identity.api;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;

import com.tooldefect.business.identity.application.LocalIdentity;

final class UserAdministrationControllerTest {
    @Test
    void usesStableLocalUserIdForAuditActor() {
        UUID userId = UUID.randomUUID();
        LocalIdentity identity = new LocalIdentity(
            userId,
            "admin",
            "系统管理员",
            "ACTIVE",
            false,
            List.of("SYSTEM_OPERATOR"),
            List.of("user:manage", "audit:read")
        );
        Authentication authentication = UsernamePasswordAuthenticationToken.authenticated(
            identity,
            "session-token",
            List.of()
        );

        assertThat(UserAdministrationController.actor(authentication))
            .isEqualTo(userId.toString())
            .hasSizeLessThanOrEqualTo(256);
        assertThat(authentication.getName()).isEqualTo(userId.toString());
    }
}
