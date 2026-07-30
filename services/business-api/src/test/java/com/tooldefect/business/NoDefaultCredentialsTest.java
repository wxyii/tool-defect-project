package com.tooldefect.business;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.security.autoconfigure.UserDetailsServiceAutoConfiguration;

/** 防止 Spring Boot 回退到随机开发口令。 */
final class NoDefaultCredentialsTest {
    @Test
    void applicationExplicitlyExcludesDefaultUserDetailsService() {
        SpringBootApplication application = ToolDefectApplication.class
            .getAnnotation(SpringBootApplication.class);

        assertThat(application).isNotNull();
        assertThat(application.exclude())
            .contains(UserDetailsServiceAutoConfiguration.class);
    }
}
