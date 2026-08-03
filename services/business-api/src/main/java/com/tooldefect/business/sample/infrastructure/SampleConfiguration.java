package com.tooldefect.business.sample.infrastructure;

import java.security.SecureRandom;
import java.time.Clock;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.Scheduled;

import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.sample.application.SampleLibraryRepository;
import com.tooldefect.business.sample.application.SampleLibraryService;
import com.tooldefect.business.sample.application.SampleLibrarySettings;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.OutboxRepository;
import com.tooldefect.business.storage.application.ObjectStoragePort;

import tools.jackson.databind.ObjectMapper;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(SampleProperties.class)
@ConditionalOnProperty(name = {"td.sample-export.enabled", "td.storage.enabled"}, havingValue = "true")
public class SampleConfiguration {
    @Bean
    SampleLibraryService sampleLibraryService(
            SampleLibraryRepository repository,
            ObjectStoragePort storage,
            IdempotencyService idempotency,
            AuditTrail audit,
            OutboxRepository outbox,
            SampleProperties properties,
            Clock clock,
            ObjectMapper json) {
        return new SampleLibraryService(repository, storage, idempotency, audit, outbox,
            new SampleLibrarySettings(properties.enabled(), properties.objectBucket(),
                properties.objectPrefix(), properties.maximumCandidates(),
                properties.maximumPackageBytes(), properties.packageRetention(),
                properties.ticketTtl()), clock, json, new SecureRandom());
    }

    @Bean
    SampleCleanupSchedule sampleCleanupSchedule(SampleLibraryService service) {
        return new SampleCleanupSchedule(service);
    }

    static final class SampleCleanupSchedule {
        private final SampleLibraryService service;

        SampleCleanupSchedule(SampleLibraryService service) {
            this.service = service;
        }

        @Scheduled(fixedDelayString = "${td.sample-export.cleanup-fixed-delay:3600000}")
        void cleanup() {
            service.cleanupExpired(UUIDs.requestId(), UUIDs.traceId());
        }
    }

    private static final class UUIDs {
        private static String requestId() {
            return java.util.UUID.randomUUID().toString();
        }

        private static String traceId() {
            return java.util.UUID.randomUUID().toString().replace("-", "");
        }
    }
}
