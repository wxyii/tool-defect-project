package com.tooldefect.business.shared.infrastructure;

import java.time.Clock;
import java.time.Duration;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.Scheduled;

import com.tooldefect.business.shared.application.ReliabilityOperationsRepository;
import com.tooldefect.business.shared.application.ReliabilityOperationsService;
import com.tooldefect.business.shared.application.Uuid7Generator;

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "td.operations.enabled", havingValue = "true")
public class ReliabilityOperationsConfiguration {
    @Bean
    ReliabilityOperationsService reliabilityOperationsService(
            ReliabilityOperationsRepository repository,
            Uuid7Generator identifiers,
            Clock clock,
            @Value("${td.operations.staging-audit-window:PT24H}")
                Duration stagingAuditWindow) {
        return new ReliabilityOperationsService(
            repository,
            identifiers,
            clock,
            stagingAuditWindow
        );
    }

    @Bean
    @ConditionalOnProperty(
        name = "td.operations.scan-enabled",
        havingValue = "true",
        matchIfMissing = true
    )
    ReliabilityScanSchedule reliabilityScanSchedule(
            ReliabilityOperationsService service,
            @Value("${td.operations.scan-batch-size:100}") int batchSize) {
        return new ReliabilityScanSchedule(service, batchSize);
    }

    static final class ReliabilityScanSchedule {
        private final ReliabilityOperationsService service;
        private final int batchSize;

        ReliabilityScanSchedule(
                ReliabilityOperationsService service,
                int batchSize) {
            this.service = service;
            this.batchSize = batchSize;
        }

        @Scheduled(fixedDelayString = "${td.operations.scan-fixed-delay:60000}")
        void scan() {
            String requestId = UUID.randomUUID().toString();
            String traceId = requestId.replace("-", "");
            service.scanDatabase(batchSize, requestId, traceId);
        }
    }
}
