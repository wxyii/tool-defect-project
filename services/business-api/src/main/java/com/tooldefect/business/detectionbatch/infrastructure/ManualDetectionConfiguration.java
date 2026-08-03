package com.tooldefect.business.detectionbatch.infrastructure;

import java.time.Clock;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.Scheduled;
import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.detectionbatch.application.ManualDetectionBatchService;
import com.tooldefect.business.detectionbatch.application.ManualDetectionRepository;
import com.tooldefect.business.detectionbatch.application.ManualDetectionSettings;
import com.tooldefect.business.detectionbatch.application.ProductionDetectionRepository;
import com.tooldefect.business.detectionbatch.application.ProductionDetectionService;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.OutboxRepository;
import com.tooldefect.business.storage.application.ObjectStoragePort;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(ManualDetectionProperties.class)
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
public class ManualDetectionConfiguration {
    @Bean
    ManualDetectionBatchService manualDetectionBatchService(ManualDetectionRepository repository,
            ObjectStoragePort storage, IdempotencyService idempotency, AuditTrail audit,
            ManualDetectionProperties properties, Clock clock, OutboxRepository outbox) {
        var settings = new ManualDetectionSettings(properties.enabled(), properties.objectBucket(),
            properties.objectPrefix(), properties.maximumItemsPerBatch(), properties.maximumObjectBytes(),
            properties.allowedMediaTypes(), properties.uploadTtl(), properties.readTtl(),
            properties.orphanRetention(), properties.cleanupBatchSize());
        return new ManualDetectionBatchService(repository, storage, idempotency, audit, settings, clock, outbox);
    }

    @Bean
    ProductionDetectionService productionDetectionService(
            ProductionDetectionRepository repository, ObjectStoragePort storage,
            IdempotencyService idempotency, OutboxRepository outbox, Clock clock) {
        return new ProductionDetectionService(repository, storage, idempotency, outbox, clock);
    }

    @Bean
    ManualOrphanSchedule manualOrphanSchedule(ManualDetectionBatchService service) {
        return new ManualOrphanSchedule(service);
    }

    static final class ManualOrphanSchedule {
        private final ManualDetectionBatchService service;
        ManualOrphanSchedule(ManualDetectionBatchService service){this.service=service;}
        @Scheduled(fixedDelayString="${td.manual-detection.cleanup-fixed-delay:60000}")
        void cleanup(){service.cleanupExpired();}
    }
}
