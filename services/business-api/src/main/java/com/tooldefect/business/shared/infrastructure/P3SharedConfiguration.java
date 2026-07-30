package com.tooldefect.business.shared.infrastructure;

import java.security.SecureRandom;
import java.time.Clock;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import com.tooldefect.business.shared.application.IdempotencyRepository;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.Uuid7Generator;

@Configuration(proxyBeanMethods = false)
public class P3SharedConfiguration {
    @Bean
    IdempotencyService idempotencyService(IdempotencyRepository repository) {
        return new IdempotencyService(repository);
    }

    @Bean
    Uuid7Generator uuid7Generator(Clock clock, SecureRandom random) {
        return new Uuid7Generator(clock, random);
    }
}
