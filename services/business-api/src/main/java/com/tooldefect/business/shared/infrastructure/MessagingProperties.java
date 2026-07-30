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
            ? new Publisher(100, Duration.ofSeconds(30), Duration.ofSeconds(10))
            : publisher;
        consumer = consumer == null
            ? new Consumer(false, "", "business-api", Duration.ofSeconds(30))
            : consumer;
    }

    public record Publisher(
        int batchSize,
        Duration claimLease,
        Duration confirmTimeout
    ) {
    }

    public record Consumer(
        boolean enabled,
        String queue,
        String name,
        Duration claimLease
    ) {
    }
}
