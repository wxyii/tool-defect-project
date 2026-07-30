package com.tooldefect.business.shared.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.lang.reflect.Proxy;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;
import org.springframework.transaction.support.TransactionTemplate;

import com.rabbitmq.client.Channel;
import com.tooldefect.business.shared.application.BusinessMessageHandler;
import com.tooldefect.business.shared.application.InboxProcessingService;
import com.tooldefect.business.shared.application.InboxRepository;
import com.tooldefect.business.shared.application.NonRetryableMessageException;
import com.tooldefect.business.shared.messaging.InboxReceipt;
import com.tooldefect.business.shared.messaging.InboxStatus;

import tools.jackson.databind.ObjectMapper;

class ManualAckInboxConsumerTest {
    private static final long DELIVERY_TAG = 42L;
    private static final UUID TASK_ID = UUID.fromString(
        "019f0000-0000-7000-8000-000000000401"
    );
    private static final Instant NOW = Instant.parse("2026-07-29T08:00:00Z");

    private FakeInboxRepository repository;
    private ChannelRecorder channel;

    @BeforeEach
    void setUp() {
        repository = new FakeInboxRepository();
        channel = new ChannelRecorder();
    }

    @Test
    void processedAndDuplicateMessagesAreAcknowledged() throws Exception {
        repository.decision = InboxRepository.Decision.PROCESS;

        consumer(payload -> { }).consume(validMessage(), channel.proxy());

        assertThat(channel.acknowledged).isTrue();
        assertThat(channel.nacked).isFalse();
        assertThat(repository.markedProcessed).isTrue();
    }

    @Test
    void busyMessageIsRequeued() throws Exception {
        repository.decision = InboxRepository.Decision.BUSY;

        consumer(payload -> { }).consume(validMessage(), channel.proxy());

        assertThat(channel.acknowledged).isFalse();
        assertThat(channel.nacked).isTrue();
        assertThat(channel.requeue).isTrue();
        assertThat(repository.markedProcessed).isFalse();
    }

    @Test
    void malformedMessageIsDeadLetteredBeforeInboxClaim() throws Exception {
        consumer(payload -> { }).consume(message("{invalid-json"), channel.proxy());

        assertThat(channel.nacked).isTrue();
        assertThat(channel.requeue).isFalse();
        assertThat(repository.claimCount).isZero();
    }

    @Test
    void nonRetryableBusinessFailureIsDeadLettered() throws Exception {
        repository.decision = InboxRepository.Decision.PROCESS;
        BusinessMessageHandler handler = payload -> {
            throw new NonRetryableMessageException("契约冲突");
        };

        consumer(handler).consume(validMessage(), channel.proxy());

        assertThat(channel.nacked).isTrue();
        assertThat(channel.requeue).isFalse();
    }

    @Test
    void transientBusinessFailureIsRequeued() throws Exception {
        repository.decision = InboxRepository.Decision.PROCESS;
        BusinessMessageHandler handler = payload -> {
            throw new IllegalStateException("暂时故障");
        };

        consumer(handler).consume(validMessage(), channel.proxy());

        assertThat(channel.nacked).isTrue();
        assertThat(channel.requeue).isTrue();
    }

    private ManualAckInboxConsumer consumer(BusinessMessageHandler handler) {
        MessagingProperties properties = new MessagingProperties(
            true,
            new MessagingProperties.Publisher(
                10,
                Duration.ofSeconds(30),
                Duration.ofSeconds(10)
            ),
            new MessagingProperties.Consumer(
                true,
                "queue",
                "business-api-test",
                Duration.ofSeconds(30)
            )
        );
        InboxProcessingService inbox = new InboxProcessingService(
            repository,
            new TransactionTemplate(new NoOpTransactionManager()),
            Clock.fixed(NOW, ZoneOffset.UTC),
            "inbox-test-owner",
            Duration.ofSeconds(30)
        );
        return new ManualAckInboxConsumer(
            inbox,
            handler,
            properties,
            new ObjectMapper()
        );
    }

    private static Message validMessage() {
        return message("""
            {
              "message_id": "019f0000-0000-7000-8000-000000000402",
              "detection_task_id": "%s",
              "result_sha256": "%s"
            }
            """.formatted(TASK_ID, "a".repeat(64)));
    }

    private static Message message(String body) {
        return MessageBuilder.withBody(body.getBytes(java.nio.charset.StandardCharsets.UTF_8))
            .setDeliveryTag(DELIVERY_TAG)
            .build();
    }

    private static final class FakeInboxRepository implements InboxRepository {
        private Decision decision = Decision.PROCESS;
        private int claimCount;
        private boolean markedProcessed;

        @Override
        public Claim claim(
                String messageId,
                String consumer,
                UUID detectionTaskId,
                String resultSha256,
                String claimOwner,
                Instant now,
                Duration leaseDuration) {
            claimCount++;
            InboxReceipt receipt = new InboxReceipt(
                messageId,
                consumer,
                detectionTaskId,
                resultSha256,
                InboxStatus.PROCESSING,
                claimOwner,
                now.plus(leaseDuration),
                1,
                now,
                null,
                null
            );
            return new Claim(decision, receipt);
        }

        @Override
        public boolean markProcessed(
                String messageId,
                String consumer,
                String claimOwner,
                Instant processedAt) {
            markedProcessed = true;
            return true;
        }
    }

    private static final class NoOpTransactionManager
            implements PlatformTransactionManager {
        @Override
        public TransactionStatus getTransaction(TransactionDefinition definition) {
            return new SimpleTransactionStatus();
        }

        @Override
        public void commit(TransactionStatus status) {
        }

        @Override
        public void rollback(TransactionStatus status) {
        }
    }

    private static final class ChannelRecorder {
        private boolean acknowledged;
        private boolean nacked;
        private boolean requeue;

        Channel proxy() {
            return (Channel) Proxy.newProxyInstance(
                Channel.class.getClassLoader(),
                new Class<?>[] {Channel.class},
                (ignored, method, arguments) -> {
                    if ("basicAck".equals(method.getName())) {
                        acknowledged = true;
                    } else if ("basicNack".equals(method.getName())) {
                        nacked = true;
                        requeue = (boolean) arguments[2];
                    }
                    return defaultValue(method.getReturnType());
                }
            );
        }

        private static Object defaultValue(Class<?> type) {
            if (!type.isPrimitive() || type == void.class) {
                return null;
            }
            if (type == boolean.class) {
                return false;
            }
            if (type == char.class) {
                return '\0';
            }
            return 0;
        }
    }
}
