package com.tooldefect.business;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.rabbitmq.RabbitMQContainer;
import org.testcontainers.utility.DockerImageName;

import com.rabbitmq.client.AMQP;
import com.rabbitmq.client.GetResponse;
import com.tooldefect.business.shared.application.InboxProcessingService;
import com.tooldefect.business.shared.application.OutboxRepository;
import com.tooldefect.business.shared.application.ReliableMessagingService;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.infrastructure.RabbitTopology;
import com.tooldefect.business.shared.messaging.OutboxEvent;

import tools.jackson.databind.ObjectMapper;

/**
 * 真实 RabbitMQ 与 PostgreSQL 上验证持久消息、发布确认、mandatory 退回、
 * 发件箱租约恢复、收件箱双重幂等以及单向死信。
 */
@SpringBootTest(
    webEnvironment = SpringBootTest.WebEnvironment.NONE,
    properties = {
        "td.storage.enabled=false",
        "td.messaging.enabled=true",
        "td.messaging.consumer.enabled=false",
        "td.messaging.publisher.scheduling-enabled=false",
        "td.messaging.publisher.confirm-timeout=PT10S",
        "spring.rabbitmq.ssl.enabled=false"
    }
)
@Testcontainers(disabledWithoutDocker = false)
class ReliableMessagingIT {
    @Container
    static final PostgreSQLContainer POSTGRES = new PostgreSQLContainer(
        DockerImageName.parse("postgres:18.4-alpine")
    )
        .withDatabaseName("tool_defect_messaging")
        .withUsername("tool_defect_test")
        .withPassword("tool-defect-test-only");

    @Container
    static final RabbitMQContainer RABBIT = new RabbitMQContainer(
        DockerImageName.parse("rabbitmq:4.1.4-management-alpine")
    )
        .withAdminUser("tool_defect_test")
        .withAdminPassword("tool-defect-rabbit-test-only");

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    RabbitTemplate rabbit;

    @Autowired
    OutboxRepository outbox;

    @Autowired
    ReliableMessagingService messaging;

    @Autowired
    InboxProcessingService inbox;

    @DynamicPropertySource
    static void infrastructureProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add(
            "spring.rabbitmq.addresses",
            () -> RABBIT.getHost() + ":" + RABBIT.getAmqpPort()
        );
        registry.add("spring.rabbitmq.username", RABBIT::getAdminUsername);
        registry.add("spring.rabbitmq.password", RABBIT::getAdminPassword);
    }

    @Test
    void confirmedOutboxRetriesMandatoryReturnAndPublishesPersistentMessage()
            throws Exception {
        Fixture fixture = seedDetectionTasks();
        rabbit.execute(channel -> channel.queueDeclarePassive(
            RabbitTopology.PRODUCTION_GPU_QUEUE
        ));

        UUID messageId = UUID.randomUUID();
        UUID eventId = UUID.randomUUID();
        outbox.append(pending(
            eventId,
            messageId,
            fixture.productionTaskId(),
            fixture,
            "production.gpu.multitask"
        ));

        assertThat(messaging.publishDue(10)).isEqualTo(1);
        assertThat(jdbc.queryForObject(
            "SELECT status FROM outbox_event WHERE event_id = ?",
            String.class,
            eventId
        )).isEqualTo("PUBLISHED");
        Message delivered = rabbit.receive(
            RabbitTopology.PRODUCTION_GPU_QUEUE,
            5_000
        );
        assertThat(delivered).isNotNull();
        assertThat(delivered.getMessageProperties().getReceivedDeliveryMode())
            .isEqualTo(MessageDeliveryMode.PERSISTENT);
        assertThat(delivered.getMessageProperties().getMessageId())
            .isEqualTo(messageId.toString());
        assertThat(delivered.getMessageProperties().getType())
            .isEqualTo("tool_defect.inference.task.v1");
        assertThat(delivered.getMessageProperties().getContentType())
            .isEqualTo("application/json");
        String schemaVersion = delivered.getMessageProperties().getHeader(
            "schema_version"
        );
        assertThat(schemaVersion)
            .isEqualTo("1.0");
        assertThat(delivered.getMessageProperties().getHeaders())
            .containsEntry("schema_version", "1.0")
            .containsKey("traceparent");
        assertThat(delivered.getMessageProperties().getHeaders().keySet())
            .filteredOn(name -> !name.startsWith("spring_"))
            .containsExactlyInAnyOrder("schema_version", "traceparent");
        var taskBody = new ObjectMapper().readTree(delivered.getBody());
        assertThat(taskBody.path("detection_task_id").stringValue())
            .isEqualTo(fixture.productionTaskId().toString());
        assertThat(taskBody.has("payload")).isFalse();

        UUID returnedEventId = UUID.randomUUID();
        outbox.append(pending(
            returnedEventId,
            UUID.randomUUID(),
            fixture.shadowTaskId(),
            fixture,
            "production.cpu.multitask"
        ));
        assertThat(messaging.publishDue(10)).isZero();
        assertThat(jdbc.queryForObject(
            "SELECT status FROM outbox_event WHERE event_id = ?",
            String.class,
            returnedEventId
        )).isEqualTo("FAILED");
        assertThat(jdbc.queryForObject(
            "SELECT last_error FROM outbox_event WHERE event_id = ?",
            String.class,
            returnedEventId
        )).contains("不可路由");

        rabbit.execute(channel -> {
            channel.queueBind(
                RabbitTopology.PRODUCTION_CPU_QUEUE,
                RabbitTopology.EXCHANGE,
                "production.cpu.multitask"
            );
            return null;
        });
        jdbc.update(
            "UPDATE outbox_event SET next_attempt_at = now() - interval '1 second' WHERE event_id = ?",
            returnedEventId
        );
        assertThat(messaging.publishDue(10)).isEqualTo(1);
        assertThat(rabbit.receive(
            RabbitTopology.PRODUCTION_CPU_QUEUE,
            5_000
        )).isNotNull();

        UUID leasedEventId = UUID.randomUUID();
        outbox.append(pending(
            leasedEventId,
            UUID.randomUUID(),
            fixture.productionTaskId(),
            fixture,
            "batch.cpu.polar"
        ));
        Instant now = Instant.now();
        var firstClaim = outbox.claimBatch(
            now,
            1,
            "publisher-one",
            Duration.ofSeconds(30)
        );
        assertThat(firstClaim).extracting(OutboxEvent::eventId)
            .containsExactly(leasedEventId);
        assertThat(outbox.claimBatch(
            now.plusSeconds(1),
            1,
            "publisher-two",
            Duration.ofSeconds(30)
        )).isEmpty();
        assertThat(outbox.claimBatch(
            now.plusSeconds(31),
            1,
            "publisher-two",
            Duration.ofSeconds(30)
        )).extracting(OutboxEvent::eventId).containsExactly(leasedEventId);
    }

    @Test
    void inboxEffectIsAtomicAndDeadLettersNeverReplayToProduction()
            throws Exception {
        Fixture fixture = seedDetectionTasks();
        jdbc.execute("""
            CREATE TABLE IF NOT EXISTS p2_message_effect (
                message_id varchar(128) PRIMARY KEY
            )
            """);
        String messageId = UUID.randomUUID().toString();
        String resultSha256 = "c".repeat(64);

        assertThat(inbox.process(
            messageId,
            "business-api-it",
            fixture.productionTaskId(),
            resultSha256,
            () -> jdbc.update(
                "INSERT INTO p2_message_effect(message_id) VALUES (?)",
                messageId
            )
        )).isEqualTo(InboxProcessingService.Result.PROCESSED);
        assertThat(inbox.process(
            messageId,
            "business-api-it",
            fixture.productionTaskId(),
            resultSha256,
            () -> jdbc.update(
                "INSERT INTO p2_message_effect(message_id) VALUES ('duplicate')"
            )
        )).isEqualTo(InboxProcessingService.Result.ALREADY_PROCESSED);
        assertThat(inbox.process(
            UUID.randomUUID().toString(),
            "business-api-it",
            fixture.productionTaskId(),
            resultSha256,
            () -> jdbc.update(
                "INSERT INTO p2_message_effect(message_id) VALUES ('task-duplicate')"
            )
        )).isEqualTo(InboxProcessingService.Result.ALREADY_PROCESSED);
        assertThat(jdbc.queryForObject(
            "SELECT COUNT(*) FROM p2_message_effect",
            Integer.class
        )).isEqualTo(1);
        assertThatThrownBy(() -> inbox.process(
            messageId,
            "business-api-it",
            fixture.productionTaskId(),
            "d".repeat(64),
            () -> { }
        )).isInstanceOf(DomainViolation.class);

        String rolledBackMessage = UUID.randomUUID().toString();
        assertThatThrownBy(() -> inbox.process(
            rolledBackMessage,
            "business-api-it",
            fixture.shadowTaskId(),
            null,
            () -> {
                jdbc.update(
                    "INSERT INTO p2_message_effect(message_id) VALUES (?)",
                    rolledBackMessage
                );
                throw new IllegalStateException("模拟业务事务失败");
            }
        )).isInstanceOf(IllegalStateException.class);
        assertThat(jdbc.queryForObject(
            "SELECT COUNT(*) FROM inbox_message WHERE message_id = ?",
            Integer.class,
            rolledBackMessage
        )).isZero();
        assertThat(jdbc.queryForObject(
            "SELECT COUNT(*) FROM p2_message_effect WHERE message_id = ?",
            Integer.class,
            rolledBackMessage
        )).isZero();

        String poisonId = UUID.randomUUID().toString();
        rabbit.execute(channel -> {
            AMQP.BasicProperties properties = new AMQP.BasicProperties.Builder()
                .contentType("application/json")
                .deliveryMode(2)
                .messageId(poisonId)
                .build();
            channel.basicPublish(
                "",
                RabbitTopology.SHADOW_GPU_QUEUE,
                false,
                properties,
                "{invalid-json".getBytes(StandardCharsets.UTF_8)
            );
            GetResponse delivery = null;
            long deadline = System.nanoTime() + Duration.ofSeconds(5).toNanos();
            while (delivery == null && System.nanoTime() < deadline) {
                delivery = channel.basicGet(
                    RabbitTopology.SHADOW_GPU_QUEUE,
                    false
                );
                if (delivery == null) {
                    Thread.onSpinWait();
                }
            }
            assertThat(delivery).isNotNull();
            channel.basicNack(
                delivery.getEnvelope().getDeliveryTag(),
                false,
                false
            );
            return null;
        });
        Message dead = rabbit.receive(RabbitTopology.DEAD_QUEUE, 5_000);
        assertThat(dead).isNotNull();
        assertThat(dead.getMessageProperties().getMessageId()).isEqualTo(poisonId);
        assertThat(rabbit.receive(
            RabbitTopology.SHADOW_GPU_QUEUE,
            250
        )).isNull();
    }

    private static OutboxEvent pending(
            UUID eventId,
            UUID messageId,
            UUID taskId,
            Fixture fixture,
            String routingKey) {
        Instant occurredAt = Instant.now();
        String traceparent =
            "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01";
        String taskPayload = """
            {
              "message_id": "%s",
              "event_type": "tool_defect.inference.task.v1",
              "occurred_at": "%s",
              "traceparent": "%s",
              "detection_task_id": "%s",
              "capture_id": "%s",
              "pipeline": {
                "pipeline_id": "%s",
                "version": "1",
                "config_sha256": "%s",
                "preprocessor_version": "1",
                "algorithm_version": "1",
                "model_version": "1"
              },
              "images": [{
                "image_id": "%s",
                "kind": "RAW",
                "object": {
                  "bucket": "td-raw",
                  "object_key": "%s",
                  "object_version": "",
                  "sha256": "%s",
                  "size_bytes": 128,
                  "media_type": "image/png"
                },
                "width": 2,
                "height": 2,
                "image_role": "PRIMARY"
              }],
              "deadline_at": "%s"
            }
            """.formatted(
                messageId,
                occurredAt,
                traceparent,
                taskId,
                fixture.captureId(),
                fixture.pipelineId(),
                "d".repeat(64),
                fixture.imageId(),
                fixture.objectKey(),
                "e".repeat(64),
                occurredAt.plusSeconds(30)
            );
        String envelope = """
            {
              "event_id": "%s",
              "event_type": "tool_defect.outbox.inference_requested.v1",
              "aggregate_type": "detection_task",
              "aggregate_id": "%s",
              "occurred_at": "%s",
              "message_id": "%s",
              "traceparent": "%s",
              "payload": %s
            }
            """.formatted(
                eventId,
                taskId,
                occurredAt,
                messageId,
                traceparent,
                taskPayload
            );
        return OutboxEvent.pending(
            eventId,
            "detection_task",
            taskId,
            "tool_defect.outbox.inference_requested.v1",
            routingKey,
            envelope,
            occurredAt
        );
    }

    private Fixture seedDetectionTasks() {
        UUID organizationId = UUID.randomUUID();
        UUID lineId = UUID.randomUUID();
        UUID recipeId = UUID.randomUUID();
        UUID stationId = UUID.randomUUID();
        UUID captureId = UUID.randomUUID();
        UUID datasetId = UUID.randomUUID();
        UUID datasetVersionId = UUID.randomUUID();
        UUID modelId = UUID.randomUUID();
        UUID modelVersionId = UUID.randomUUID();
        UUID pipelineId = UUID.randomUUID();
        UUID imageId = UUID.randomUUID();
        UUID productionTaskId = UUID.randomUUID();
        UUID shadowTaskId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO organization(
                organization_id, organization_code, organization_name, status
            ) VALUES (?, ?, '消息测试组织', 'ACTIVE')
            """,
            organizationId,
            "message-org-" + organizationId
        );
        jdbc.update(
            """
            INSERT INTO production_line(
                line_id, organization_id, line_code, line_name, status
            ) VALUES (?, ?, ?, '消息测试产线', 'ACTIVE')
            """,
            lineId,
            organizationId,
            "message-line-" + lineId
        );
        jdbc.update(
            """
            INSERT INTO capture_recipe(
                recipe_id, recipe_name, version, config,
                config_sha256, status
            ) VALUES (?, ?, '1', '{}'::jsonb, ?, 'APPROVED')
            """,
            recipeId,
            "message-recipe-" + recipeId,
            "a".repeat(64)
        );
        jdbc.update(
            """
            INSERT INTO station(
                station_id, line_id, station_code, station_name,
                active_recipe_id, status
            ) VALUES (?, ?, ?, '消息测试工位', ?, 'ACTIVE')
            """,
            stationId,
            lineId,
            "message-station-" + stationId,
            recipeId
        );
        jdbc.update(
            """
            INSERT INTO capture_event(
                capture_id, station_id, trigger_id, client_sequence,
                source_type, captured_at, recipe_id, status,
                quality_status, request_digest
            ) VALUES (?, ?, ?, 1, 'ONLINE', now(), ?, 'SUBMITTED', 'OK', ?)
            """,
            captureId,
            stationId,
            "message-trigger-" + captureId,
            recipeId,
            "b".repeat(64)
        );
        String objectKey = "raw/2026/07/29/" + stationId + "/"
            + captureId + "/primary-e.png";
        jdbc.update(
            """
            INSERT INTO image_object(
                image_id, capture_id, kind, bucket, object_key,
                object_version, sha256, size_bytes, media_type,
                width, height, state
            ) VALUES (?, ?, 'RAW', 'td-raw', ?, '', ?, 128,
                'image/png', 2, 2, 'AVAILABLE')
            """,
            imageId,
            captureId,
            objectKey,
            "e".repeat(64)
        );
        jdbc.update(
            "INSERT INTO dataset(dataset_id, dataset_name, purpose) VALUES (?, ?, '消息测试')",
            datasetId,
            "message-dataset-" + datasetId
        );
        jdbc.update(
            """
            INSERT INTO dataset_version(
                dataset_version_id, dataset_id, version, status
            ) VALUES (?, ?, '1', 'BUILDING')
            """,
            datasetVersionId,
            datasetId
        );
        jdbc.update(
            "INSERT INTO model(model_id, model_name, task_type) VALUES (?, ?, 'MULTITASK')",
            modelId,
            "message-model-" + modelId
        );
        jdbc.update(
            """
            INSERT INTO model_version(
                model_version_id, model_id, version, dataset_version_id,
                artifact_bucket, artifact_object_key, artifact_sha256,
                input_spec, output_spec, approval_state
            ) VALUES (?, ?, '1', ?, 'td-models', ?, ?,
                '{}'::jsonb, '{}'::jsonb, 'CANDIDATE')
            """,
            modelVersionId,
            modelId,
            datasetVersionId,
            "models/" + modelVersionId + "/model.bin",
            "c".repeat(64)
        );
        jdbc.update(
            """
            INSERT INTO pipeline_version(
                pipeline_id, pipeline_name, version,
                preprocessor_id, preprocessor_version,
                algorithm_id, algorithm_version, model_version_id,
                config, config_sha256, status
            ) VALUES (?, ?, '1', 'pre', '1', 'algo', '1', ?,
                '{}'::jsonb, ?, 'APPROVED')
            """,
            pipelineId,
            "message-pipeline-" + pipelineId,
            modelVersionId,
            "d".repeat(64)
        );
        insertTask(jdbc, productionTaskId, captureId, pipelineId, "PRODUCTION");
        insertTask(jdbc, shadowTaskId, captureId, pipelineId, "SHADOW");
        return new Fixture(
            productionTaskId,
            shadowTaskId,
            captureId,
            pipelineId,
            imageId,
            objectKey
        );
    }

    private static void insertTask(
            JdbcTemplate jdbc,
            UUID taskId,
            UUID captureId,
            UUID pipelineId,
            String purpose) {
        jdbc.update(
            """
            INSERT INTO detection_task(
                detection_task_id, capture_id, pipeline_id,
                purpose, status, priority
            ) VALUES (?, ?, ?, ?, 'QUEUED', 10)
            """,
            taskId,
            captureId,
            pipelineId,
            purpose
        );
    }

    private record Fixture(
        UUID productionTaskId,
        UUID shadowTaskId,
        UUID captureId,
        UUID pipelineId,
        UUID imageId,
        String objectKey
    ) {
    }
}
