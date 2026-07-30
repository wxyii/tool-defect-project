package com.tooldefect.business.shared.infrastructure;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "td.messaging")
public record MessagingProperties(
        boolean enabled,
        Publisher publisher,
        Consumer consumer) {

    public MessagingProperties {
        publisher = publisher == null
            ? new Publisher(
                100,
                Duration.ofSeconds(30),
                Duration.ofSeconds(10),
                10,
                Duration.ofSeconds(1),
                Duration.ofMinutes(5),
                0.2
            )
            : publisher;
        consumer = consumer == null
            ? new Consumer(false, "", "business-api", Duration.ofSeconds(30))
            : consumer;
    }

    public record Publisher(
        int batchSize,
        Duration claimLease,
        Duration confirmTimeout,
        int maximumAttempts,
        Duration initialBackoff,
        Duration maximumBackoff,
        double jitterRatio
    ) {
        public Publisher(
                int batchSize,
                Duration claimLease,
                Duration confirmTimeout) {
            this(
                batchSize,
                claimLease,
                confirmTimeout,
                10,
                Duration.ofSeconds(1),
                Duration.ofMinutes(5),
                0.2
            );
        }
    }

    public record Consumer(
        boolean enabled,
        String queue,
        String name,
        Duration claimLease
    ) {
    }
}
