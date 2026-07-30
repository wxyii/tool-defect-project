package com.tooldefect.business.shared.infrastructure;

import java.lang.management.ManagementFactory;
import java.time.Clock;
import java.util.UUID;

import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import tools.jackson.databind.ObjectMapper;

import com.tooldefect.business.shared.application.InboxProcessingService;
import com.tooldefect.business.shared.application.InboxRepository;
import com.tooldefect.business.shared.application.OutboxRepository;
import com.tooldefect.business.shared.application.ReliableMessagingService;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(MessagingProperties.class)
@ConditionalOnProperty(name = "td.messaging.enabled", havingValue = "true")
public class MessagingConfiguration {
    @Bean
    RabbitMessagePublisher rabbitMessagePublisher(
            RabbitTemplate rabbit,
            MessagingProperties properties,
            ObjectMapper json) {
        rabbit.setMandatory(true);
        return new RabbitMessagePublisher(
            rabbit,
            properties.publisher().confirmTimeout(),
            json
        );
    }

    @Bean
    ReliableMessagingService reliableMessagingService(
            OutboxRepository outbox,
            RabbitMessagePublisher publisher,
            Clock clock,
            MessagingProperties properties) {
        return new ReliableMessagingService(
            outbox,
            publisher,
            clock,
            processOwner("outbox"),
            properties.publisher().claimLease()
        );
    }

    @Bean
    InboxProcessingService inboxProcessingService(
            InboxRepository inbox,
            PlatformTransactionManager transactionManager,
            Clock clock,
            MessagingProperties properties) {
        return new InboxProcessingService(
            inbox,
            new TransactionTemplate(transactionManager),
            clock,
            processOwner("inbox"),
            properties.consumer().claimLease()
        );
    }

    @Bean
    @ConditionalOnProperty(
        name = "td.messaging.publisher.scheduling-enabled",
        havingValue = "true",
        matchIfMissing = true
    )
    OutboxSchedule outboxSchedule(
            ReliableMessagingService messaging,
            MessagingProperties properties) {
        return new OutboxSchedule(messaging, properties.publisher().batchSize());
    }

    static final class OutboxSchedule {
        private final ReliableMessagingService messaging;
        private final int batchSize;

        OutboxSchedule(ReliableMessagingService messaging, int batchSize) {
            this.messaging = messaging;
            this.batchSize = batchSize;
        }

        @Scheduled(fixedDelayString = "${td.messaging.publisher.fixed-delay:1000}")
        void publishDue() {
            messaging.publishDue(batchSize);
        }
    }

    private static String processOwner(String purpose) {
        return purpose
            + "-"
            + ManagementFactory.getRuntimeMXBean().getName()
            + "-"
            + UUID.randomUUID();
    }
}
