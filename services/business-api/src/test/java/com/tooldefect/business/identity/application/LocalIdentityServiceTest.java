package com.tooldefect.business.identity.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import com.tooldefect.business.audit.application.AuditTrail;

final class LocalIdentityServiceTest {
    private final LocalIdentityService service = new LocalIdentityService(
        new JdbcTemplate(),
        mock(AuditTrail.class),
        "",
        "",
        ""
    );

    @Test
    void usernameIsCanonicalAndStrict() {
        assertThat(service.normalizeUsername("Operator_01"))
            .isEqualTo("operator_01");
        assertThatThrownBy(() -> service.normalizeUsername(" op "))
            .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.normalizeUsername("ab"))
            .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void passwordPolicyRejectsShortLongAndUsernamePasswords() {
        assertThatThrownBy(() ->
            service.validatePassword("operator", "short"))
            .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() ->
            service.validatePassword("operator-account", "operator-account"))
            .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() ->
            service.validatePassword("operator", "x".repeat(129)))
            .isInstanceOf(IllegalArgumentException.class);
        service.validatePassword("operator", "valid-password-123");
    }
}
