package com.tooldefect.business;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;

import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationVersion;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

import com.tooldefect.business.detection.domain.DetectionNotFound;
import com.tooldefect.business.detection.infrastructure.JdbcDetectionQueryRepository;
import com.tooldefect.business.review.domain.ReviewStatus;
import com.tooldefect.business.review.infrastructure.JdbcReviewRepository;

/**
 * 真实 PostgreSQL 上验证空库、向前迁移、约束以及备份恢复。Docker 不可用时
 * 不允许跳过：严格门禁必须以失败暴露缺失的前置条件。
 */
@Testcontainers(disabledWithoutDocker = false)
class DatabaseMigrationIT {
    @Container
    static final PostgreSQLContainer POSTGRES = new PostgreSQLContainer(
        DockerImageName.parse("postgres:18.4-alpine")
    )
        .withDatabaseName("tool_defect")
        .withUsername("tool_defect_test")
        .withPassword("tool-defect-test-only");

    @Test
    void emptyDatabaseMigratesAndContainsNoBinaryColumns() {
        String schema = uniqueName("empty");
        Flyway flyway = flyway(POSTGRES.getJdbcUrl(), schema, null);

        var result = flyway.migrate();

        assertThat(result.migrationsExecuted).isEqualTo(5);
        flyway.validate();
        JdbcTemplate jdbc = jdbc(POSTGRES.getJdbcUrl(), schema);
        assertThat(jdbc.queryForObject(
            """
            SELECT COUNT(*)
            FROM flyway_schema_history
            WHERE success AND version IS NOT NULL
            """,
            Integer.class
        )).isEqualTo(5);
        assertThat(jdbc.queryForObject(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = ?
              AND data_type = 'bytea'
            """,
            Integer.class,
            schema
        )).isZero();
        assertThat(jdbc.queryForObject(
            "SELECT to_regclass(?) IS NOT NULL",
            Boolean.class,
            schema + ".upload_session"
        )).isTrue();
    }

    @Test
    void existingV2RowsMigrateForwardWithoutPretendingClaimsSucceeded() {
        String schema = uniqueName("forward");
        Flyway v2 = flyway(
            POSTGRES.getJdbcUrl(),
            schema,
            MigrationVersion.fromVersion("2")
        );
        assertThat(v2.migrate().migrationsExecuted).isEqualTo(2);
        JdbcTemplate jdbc = jdbc(POSTGRES.getJdbcUrl(), schema);
        UUID lineId = UUID.randomUUID();
        UUID aggregateId = UUID.randomUUID();
        UUID eventId = UUID.randomUUID();
        UUID recipeId = UUID.randomUUID();
        UUID stationId = UUID.randomUUID();
        UUID captureId = UUID.randomUUID();
        UUID reviewTaskId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO production_line(line_id, line_code, line_name, status)
            VALUES (?, 'legacy-line', '旧产线', 'ACTIVE')
            """,
            lineId
        );
        jdbc.update(
            """
            INSERT INTO capture_recipe(
                recipe_id, recipe_name, version, config,
                config_sha256, status
            ) VALUES (?, ?, '1', '{}'::jsonb, ?, 'APPROVED')
            """,
            recipeId,
            "legacy-recipe-" + recipeId,
            "a".repeat(64)
        );
        jdbc.update(
            """
            INSERT INTO station(
                station_id, line_id, station_code, station_name,
                active_recipe_id, status
            ) VALUES (?, ?, ?, '旧工位', ?, 'ACTIVE')
            """,
            stationId,
            lineId,
            "legacy-station-" + stationId,
            recipeId
        );
        jdbc.update(
            """
            INSERT INTO capture_event(
                capture_id, station_id, trigger_id, client_sequence,
                source_type, captured_at, recipe_id, status,
                quality_status, request_digest
            ) VALUES (?, ?, ?, 1, 'ONLINE', now(), ?, 'CREATED', 'OK', ?)
            """,
            captureId,
            stationId,
            "legacy-trigger-" + captureId,
            recipeId,
            "b".repeat(64)
        );
        jdbc.update(
            """
            INSERT INTO review_task(
                review_task_id, capture_id, priority,
                status, trigger_reasons
            ) VALUES (?, ?, 10, 'COMPLETED', '[]'::jsonb)
            """,
            reviewTaskId,
            captureId
        );
        jdbc.update(
            """
            INSERT INTO outbox_event(
                event_id, aggregate_type, aggregate_id, event_type,
                payload, status
            ) VALUES (?, 'detection_task', ?, 'DetectionRequested.v1',
                CAST(? AS jsonb), 'CLAIMED')
            """,
            eventId,
            aggregateId,
            "{\"message_id\":\"" + UUID.randomUUID() + "\"}"
        );
        jdbc.update(
            """
            INSERT INTO inbox_message(message_id, consumer, status)
            VALUES ('legacy-message', 'business-api', 'PROCESSING')
            """
        );

        Flyway latest = flyway(POSTGRES.getJdbcUrl(), schema, null);
        assertThat(latest.migrate().migrationsExecuted).isEqualTo(3);

        assertThat(jdbc.queryForObject(
            "SELECT organization_id FROM production_line WHERE line_id = ?",
            UUID.class,
            lineId
        )).isEqualTo(UUID.fromString("00000000-0000-7000-8000-000000000000"));
        assertThat(jdbc.queryForObject(
            "SELECT status FROM outbox_event WHERE event_id = ?",
            String.class,
            eventId
        )).isEqualTo("FAILED");
        assertThat(jdbc.queryForObject(
            "SELECT status FROM review_task WHERE review_task_id = ?",
            String.class,
            reviewTaskId
        )).isEqualTo("RESOLVED");
        assertThat(jdbc.queryForObject(
            """
            SELECT claim_owner IS NULL AND lease_until IS NULL
            FROM outbox_event WHERE event_id = ?
            """,
            Boolean.class,
            eventId
        )).isTrue();
        assertThat(jdbc.queryForObject(
            """
            SELECT status FROM inbox_message
            WHERE message_id = 'legacy-message' AND consumer = 'business-api'
            """,
            String.class
        )).isEqualTo("FAILED");
    }

    @Test
    void databaseEnforcesVersionIntegrityAvailabilityAndAppendOnlyFacts() {
        String schema = uniqueName("constraints");
        flyway(POSTGRES.getJdbcUrl(), schema, null).migrate();
        JdbcTemplate jdbc = jdbc(POSTGRES.getJdbcUrl(), schema);
        Fixture fixture = seedCapture(jdbc);

        assertThat(jdbc.update(
            """
            INSERT INTO review_task(
                review_task_id, capture_id, priority,
                status, trigger_reasons
            ) VALUES (?, ?, 10, 'ESCALATED', '[]'::jsonb)
            """,
            UUID.randomUUID(),
            fixture.captureId()
        )).isEqualTo(1);
        assertThatThrownBy(() -> jdbc.update(
            """
            INSERT INTO review_task(
                review_task_id, capture_id, priority,
                status, trigger_reasons
            ) VALUES (?, ?, 10, 'COMPLETED', '[]'::jsonb)
            """,
            UUID.randomUUID(),
            fixture.captureId()
        )).isInstanceOf(DataAccessException.class);

        String lineCode = jdbc.queryForObject(
            "SELECT line_code FROM production_line WHERE line_id = ?",
            String.class,
            fixture.lineId()
        );
        assertThatThrownBy(() -> jdbc.update(
            """
            INSERT INTO production_line(
                line_id, organization_id, line_code, line_name, status
            ) VALUES (?, ?, ?, '重复产线', 'ACTIVE')
            """,
            UUID.randomUUID(),
            fixture.organizationId(),
            lineCode
        )).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(() -> jdbc.update(
            """
            INSERT INTO device(
                device_id, station_id, device_type, status
            ) VALUES (?, ?, 'CAMERA', 'ONLINE')
            """,
            UUID.randomUUID(),
            UUID.randomUUID()
        )).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(() -> jdbc.update(
            """
            INSERT INTO capture_event(
                capture_id, station_id, trigger_id, client_sequence,
                source_type, captured_at, recipe_id, status,
                quality_status, request_digest
            ) VALUES (?, ?, 'illegal-finalized', 2, 'ONLINE', now(), ?,
                'FINALIZED', 'OK', ?)
            """,
            UUID.randomUUID(),
            fixture.stationId(),
            fixture.recipeId(),
            "9".repeat(64)
        )).isInstanceOf(DataAccessException.class);

        assertThatThrownBy(() -> jdbc.update(
            """
            INSERT INTO detection_result(
                detection_result_id, detection_task_id, accepted_attempt_id,
                schema_version, algorithm_outcome, confidence,
                qualified_probability, unqualified_probability,
                preprocess_quality, standard_result, result_sha256
            ) VALUES (?, ?, ?, '1', 'QUALIFIED', 1.1,
                0.5, 0.5, 'OK', '{}'::jsonb, ?)
            """,
            UUID.randomUUID(),
            fixture.detectionTaskId(),
            fixture.attemptId(),
            "8".repeat(64)
        )).isInstanceOf(DataAccessException.class);
        assertThat(jdbc.update(
            """
            INSERT INTO detection_result(
                detection_result_id, detection_task_id, accepted_attempt_id,
                schema_version, algorithm_outcome, confidence,
                qualified_probability, unqualified_probability,
                preprocess_quality, standard_result, result_sha256
            ) VALUES (?, ?, ?, '1', 'QUALIFIED', 0.8,
                0.8, 0.2, 'OK', '{}'::jsonb, ?)
            """,
            UUID.randomUUID(),
            fixture.detectionTaskId(),
            fixture.attemptId(),
            "7".repeat(64)
        )).isEqualTo(1);
        assertThatThrownBy(() -> jdbc.update(
            "UPDATE detection_attempt SET status = 'FAILED' WHERE attempt_id = ?",
            fixture.attemptId()
        )).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(() -> jdbc.update(
            "UPDATE detection_attempt SET worker_id = 'tampered' WHERE attempt_id = ?",
            fixture.attemptId()
        )).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(() -> jdbc.update(
            "DELETE FROM detection_attempt WHERE attempt_id = ?",
            fixture.attemptId()
        )).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(() -> jdbc.update(
            """
            INSERT INTO detection_result(
                detection_result_id, detection_task_id, accepted_attempt_id,
                schema_version, algorithm_outcome,
                qualified_probability, unqualified_probability,
                preprocess_quality, standard_result, result_sha256
            ) VALUES (?, ?, ?, '1', 'QUALIFIED', 0.7, 0.3,
                'OK', '{}'::jsonb, ?)
            """,
            UUID.randomUUID(),
            fixture.detectionTaskId(),
            fixture.attemptId(),
            "6".repeat(64)
        )).isInstanceOf(DataAccessException.class);

        assertThatThrownBy(() -> jdbc.update(
            "UPDATE production_line SET line_name = '越过乐观锁' WHERE line_id = ?",
            fixture.lineId()
        )).isInstanceOf(DataAccessException.class);
        assertThat(jdbc.update(
            """
            UPDATE production_line
            SET line_name = '受控更新', record_version = record_version + 1
            WHERE line_id = ?
            """,
            fixture.lineId()
        )).isEqualTo(1);

        assertThatThrownBy(() -> jdbc.update(
            """
            INSERT INTO outbox_event(
                event_id, aggregate_type, aggregate_id, event_type,
                routing_key, payload, status
            ) VALUES (?, 'capture', ?, 'CaptureCreated.v1',
                'production.gpu.multitask', CAST(? AS jsonb), 'NEW')
            """,
            UUID.randomUUID(),
            fixture.captureId(),
            "{\"base64\":\"forbidden\"}"
        )).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(() -> jdbc.update(
            """
            INSERT INTO outbox_event(
                event_id, aggregate_type, aggregate_id, event_type,
                routing_key, payload, status
            ) VALUES (?, 'capture', ?, 'CaptureCreated.v1',
                'production.gpu.multitask', CAST(? AS jsonb), 'NEW')
            """,
            UUID.randomUUID(),
            fixture.captureId(),
            "{\"payload\":{\"" + '\\' + "u0062ase64\":\"forbidden\"}}"
        )).isInstanceOf(DataAccessException.class);

        UUID imageId = insertImage(jdbc, fixture.captureId(), "staging/image.png");
        assertThatThrownBy(() -> jdbc.update(
            """
            UPDATE image_object
            SET state = 'AVAILABLE', record_version = record_version + 1
            WHERE image_id = ?
            """,
            imageId
        )).isInstanceOf(DataAccessException.class);
        assertThat(jdbc.update(
            """
            UPDATE image_object
            SET state = 'AVAILABLE', width = 2, height = 3,
                record_version = record_version + 1
            WHERE image_id = ?
            """,
            imageId
        )).isEqualTo(1);
        assertThatThrownBy(() -> jdbc.update(
            """
            UPDATE image_object
            SET width = NULL, record_version = record_version + 1
            WHERE image_id = ?
            """,
            imageId
        )).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(() -> jdbc.update(
            """
            UPDATE image_object
            SET sha256 = ?, record_version = record_version + 1
            WHERE image_id = ?
            """,
            "b".repeat(64),
            imageId
        )).isInstanceOf(DataAccessException.class);

        UUID unavailable = insertImage(
            jdbc,
            fixture.captureId(),
            "staging/not-available.png"
        );
        UUID datasetVersionId = seedDatasetVersion(jdbc);
        assertThatThrownBy(() -> jdbc.update(
            """
            INSERT INTO dataset_sample(
                dataset_sample_id, dataset_version_id, sample_key,
                capture_id, image_id, label, split, content_sha256, group_key
            ) VALUES (?, ?, 'sample-1', ?, ?, 'OK', 'TRAIN', ?, 'group-1')
            """,
            UUID.randomUUID(),
            datasetVersionId,
            fixture.captureId(),
            unavailable,
            "c".repeat(64)
        )).isInstanceOf(DataAccessException.class);
        UUID datasetSampleId = UUID.randomUUID();
        assertThat(jdbc.update(
            """
            INSERT INTO dataset_sample(
                dataset_sample_id, dataset_version_id, sample_key,
                capture_id, image_id, label, split, content_sha256, group_key
            ) VALUES (?, ?, 'sample-2', ?, ?, 'OK', 'TRAIN', ?, 'group-1')
            """,
            datasetSampleId,
            datasetVersionId,
            fixture.captureId(),
            imageId,
            "d".repeat(64)
        )).isEqualTo(1);
        assertThat(jdbc.update(
            """
            UPDATE dataset_version
            SET manifest_bucket = 'td-datasets',
                manifest_object_key = 'manifests/frozen-v1.json',
                manifest_sha256 = ?,
                status = 'VALIDATING'
            WHERE dataset_version_id = ?
            """,
            "4".repeat(64),
            datasetVersionId
        )).isEqualTo(1);
        assertThat(jdbc.update(
            """
            UPDATE dataset_version SET status = 'FROZEN'
            WHERE dataset_version_id = ?
            """,
            datasetVersionId
        )).isEqualTo(1);
        UUID mutableDatasetVersionId = UUID.randomUUID();
        assertThat(jdbc.update(
            """
            INSERT INTO dataset_version(
                dataset_version_id, dataset_id, version, status
            )
            SELECT ?, dataset_id, '2', 'BUILDING'
            FROM dataset_version WHERE dataset_version_id = ?
            """,
            mutableDatasetVersionId,
            datasetVersionId
        )).isEqualTo(1);
        assertThatThrownBy(() -> jdbc.update(
            """
            UPDATE dataset_sample SET dataset_version_id = ?
            WHERE dataset_sample_id = ?
            """,
            mutableDatasetVersionId,
            datasetSampleId
        )).isInstanceOf(DataAccessException.class);
        assertThatThrownBy(() -> jdbc.update(
            "DELETE FROM dataset_sample WHERE dataset_sample_id = ?",
            datasetSampleId
        )).isInstanceOf(DataAccessException.class);

        UUID firstDispositionId = UUID.randomUUID();
        assertThat(jdbc.update(
            """
            INSERT INTO disposition_record(
                disposition_id, capture_id, source, disposition,
                policy_version, reason_code, policy_snapshot,
                input_summary_sha256
            ) VALUES (?, ?, 'AUTO', 'PASS', 'policy-v1', 'AUTO_PASS',
                '{"threshold":0.8}'::jsonb, ?)
            """,
            firstDispositionId,
            fixture.captureId(),
            "1".repeat(64)
        )).isEqualTo(1);
        assertThat(jdbc.update(
            """
            UPDATE capture_event
            SET status = 'FINALIZED',
                current_disposition = 'PASS',
                current_disposition_id = ?,
                record_version = record_version + 1
            WHERE capture_id = ?
            """,
            firstDispositionId,
            fixture.captureId()
        )).isEqualTo(1);
        assertThatThrownBy(() -> jdbc.update(
            """
            UPDATE capture_event
            SET trigger_id = 'tampered-after-finalized',
                record_version = record_version + 1
            WHERE capture_id = ?
            """,
            fixture.captureId()
        )).isInstanceOf(DataAccessException.class);
        UUID correctedDispositionId = UUID.randomUUID();
        assertThat(jdbc.update(
            """
            INSERT INTO disposition_record(
                disposition_id, capture_id, source, disposition,
                policy_version, reason_code, supersedes_id,
                policy_snapshot, input_summary_sha256
            ) VALUES (?, ?, 'AUTO', 'FAIL', 'policy-correction-v1',
                'CORRECTION', ?, '{"correction":true}'::jsonb, ?)
            """,
            correctedDispositionId,
            fixture.captureId(),
            firstDispositionId,
            "2".repeat(64)
        )).isEqualTo(1);
        assertThat(jdbc.update(
            """
            UPDATE capture_event
            SET current_disposition = 'FAIL',
                current_disposition_id = ?,
                record_version = record_version + 1
            WHERE capture_id = ?
            """,
            correctedDispositionId,
            fixture.captureId()
        )).isEqualTo(1);

        UUID auditId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO audit_log(
                audit_id, occurred_at, actor_type, actor_id, action,
                resource_type, resource_id, request_id, trace_id, result
            ) VALUES (?, now(), 'SYSTEM', 'migration-it', 'VERIFY',
                'capture', ?, 'request-1', ?, 'SUCCESS')
            """,
            auditId,
            fixture.captureId().toString(),
            "e".repeat(32)
        );
        assertThatThrownBy(() -> jdbc.update(
            "UPDATE audit_log SET result = 'TAMPERED' WHERE audit_id = ?",
            auditId
        )).isInstanceOf(DataAccessException.class);
    }

    @Test
    void detectionQueriesAlwaysAppendDatabaseDataScope() {
        String schema = uniqueName("detection_query");
        flyway(POSTGRES.getJdbcUrl(), schema, null).migrate();
        JdbcTemplate jdbc = jdbc(POSTGRES.getJdbcUrl(), schema);
        Fixture fixture = seedCapture(jdbc);
        var queries = new JdbcDetectionQueryRepository(jdbc);

        Map<String, Object> deniedPage = queries.list(
            "subject-without-scope",
            null,
            25,
            null,
            null,
            null
        );
        assertThat((java.util.List<?>) deniedPage.get("items")).isEmpty();
        assertThatThrownBy(() ->
            queries.detail(
                "subject-without-scope",
                fixture.detectionTaskId()
            )
        ).isInstanceOf(DetectionNotFound.class);

        seedDetectionReaderScope(jdbc, "authorized-subject", fixture.stationId());
        Map<String, Object> page = queries.list(
            "authorized-subject",
            null,
            25,
            null,
            null,
            null
        );
        assertThat((java.util.List<?>) page.get("items")).hasSize(1);
        Map<String, Object> detail = queries.detail(
            "authorized-subject",
            fixture.detectionTaskId()
        );
        assertThat(
            ((Map<?, ?>) detail.get("capture")).get("capture_id")
        ).isEqualTo(fixture.captureId().toString());
        assertThat(detail).containsOnlyKeys(
            "capture",
            "detection",
            "attempts",
            "disposition_history",
            "images",
            "versions"
        );
    }

    @Test
    void reviewPoolScopeConcurrentClaimAndExpiredLeaseAreDatabaseBacked()
            throws Exception {
        String schema = uniqueName("review_pool");
        flyway(POSTGRES.getJdbcUrl(), schema, null).migrate();
        JdbcTemplate jdbc = jdbc(POSTGRES.getJdbcUrl(), schema);
        Fixture fixture = seedCapture(jdbc);
        UUID reviewTaskId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO review_task(
                review_task_id, capture_id, priority,
                status, trigger_reasons
            ) VALUES (?, ?, 10, 'PENDING', '["LOW_CONFIDENCE"]'::jsonb)
            """,
            reviewTaskId,
            fixture.captureId()
        );
        seedScopedPermission(
            jdbc,
            List.of("reviewer-one", "reviewer-two"),
            "review:read",
            fixture.stationId()
        );
        seedScopedPermission(
            jdbc,
            List.of("reviewer-one", "reviewer-two"),
            "review:claim",
            fixture.stationId()
        );
        var first = new JdbcReviewRepository(jdbc);
        var second = new JdbcReviewRepository(jdbc);
        assertThat((List<?>) first.list(
            "subject-without-scope",
            null,
            25,
            null
        ).get("items")).isEmpty();
        assertThat((List<?>) first.list(
            "reviewer-one",
            null,
            25,
            ReviewStatus.PENDING.name()
        ).get("items")).hasSize(1);

        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        try (var workers = Executors.newFixedThreadPool(2)) {
            var claimOne = workers.submit(() -> {
                ready.countDown();
                start.await();
                return first.claim(
                    reviewTaskId,
                    "reviewer-one",
                    0,
                    Instant.parse("2026-07-30T08:05:00Z"),
                    "PENDING"
                );
            });
            var claimTwo = workers.submit(() -> {
                ready.countDown();
                start.await();
                return second.claim(
                    reviewTaskId,
                    "reviewer-two",
                    0,
                    Instant.parse("2026-07-30T08:05:00Z"),
                    "PENDING"
                );
            });
            ready.await();
            start.countDown();
            assertThat(List.of(claimOne.get(), claimTwo.get()))
                .containsExactlyInAnyOrder(true, false);
        }

        first.requeueExpired(Instant.parse("2026-07-30T08:05:01Z"));
        var requeued = first.requireAuthorized(
            "reviewer-one",
            reviewTaskId,
            "review:read",
            false
        );
        assertThat(requeued.status()).isEqualTo(ReviewStatus.PENDING);
        assertThat(requeued.claimedBy()).isNull();
        assertThat(requeued.recordVersion()).isEqualTo(2);
        assertThatThrownBy(() -> jdbc.update(
            """
            INSERT INTO review_task(
                review_task_id, capture_id, priority,
                status, trigger_reasons
            ) VALUES (?, ?, 15, 'PENDING', '[]'::jsonb)
            """,
            UUID.randomUUID(),
            fixture.captureId()
        )).isInstanceOf(DataAccessException.class);
    }

    @Test
    void humanReviewFactsAndTrainingApprovalAreDatabaseEnforced() {
        String schema = uniqueName("review_facts");
        flyway(POSTGRES.getJdbcUrl(), schema, null).migrate();
        JdbcTemplate jdbc = jdbc(POSTGRES.getJdbcUrl(), schema);
        Fixture fixture = seedCapture(jdbc);
        UUID reviewerId = seedUser(jdbc, "review-record-owner");
        UUID qualityId = seedUser(jdbc, "quality-approver");
        UUID taskId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO review_task(
                review_task_id, capture_id, priority,
                status, trigger_reasons
            ) VALUES (?, ?, 10, 'RESOLVED', '["MANUAL_SAMPLE"]'::jsonb)
            """,
            taskId,
            fixture.captureId()
        );

        assertThatThrownBy(() -> insertReviewRecord(
            jdbc,
            UUID.randomUUID(),
            taskId,
            reviewerId,
            "PASS",
            "OTHER",
            ""
        )).isInstanceOf(DataAccessException.class);
        UUID reviewRecordId = UUID.randomUUID();
        insertReviewRecord(
            jdbc,
            reviewRecordId,
            taskId,
            reviewerId,
            "PASS",
            "CONFIRMED_CORRECT",
            "证据完整"
        );
        assertThatThrownBy(() -> jdbc.update(
            "UPDATE review_record SET comment = '篡改' WHERE review_record_id = ?",
            reviewRecordId
        )).isInstanceOf(DataAccessException.class);

        UUID rawImageId = insertImage(
            jdbc,
            fixture.captureId(),
            "review-training/raw.png"
        );
        jdbc.update(
            """
            UPDATE image_object
            SET state = 'AVAILABLE', width = 2, height = 3,
                record_version = record_version + 1
            WHERE image_id = ?
            """,
            rawImageId
        );
        UUID datasetVersionId = seedDatasetVersion(jdbc);
        assertThatThrownBy(() -> insertReviewDatasetSample(
            jdbc,
            UUID.randomUUID(),
            datasetVersionId,
            fixture.captureId(),
            rawImageId,
            reviewRecordId,
            "before-approval"
        )).isInstanceOf(DataAccessException.class);

        UUID trainingDecisionId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO review_training_decision(
                training_decision_id, review_record_id,
                decision, decided_by, reason
            ) VALUES (?, ?, 'APPROVED', ?, '质量负责人批准进入训练候选')
            """,
            trainingDecisionId,
            reviewRecordId,
            qualityId
        );
        assertThat(insertReviewDatasetSample(
            jdbc,
            UUID.randomUUID(),
            datasetVersionId,
            fixture.captureId(),
            rawImageId,
            reviewRecordId,
            "after-approval"
        )).isEqualTo(1);
        assertThatThrownBy(() -> jdbc.update(
            """
            UPDATE review_training_decision
            SET decision = 'REJECTED'
            WHERE training_decision_id = ?
            """,
            trainingDecisionId
        )).isInstanceOf(DataAccessException.class);
    }

    @Test
    void pgDumpRestoresSchemaHistoryAndBusinessRows() throws Exception {
        String sourceDatabase = uniqueName("backup_source");
        String restoredDatabase = uniqueName("backup_restored");
        createDatabase(sourceDatabase);
        String sourceUrl = databaseUrl(sourceDatabase);
        flyway(sourceUrl, "public", null).migrate();
        JdbcTemplate source = jdbc(sourceUrl, "public");
        UUID organizationId = UUID.randomUUID();
        source.update(
            """
            INSERT INTO organization(
                organization_id, organization_code, organization_name, status
            ) VALUES (?, 'backup-proof', '备份验证组织', 'ACTIVE')
            """,
            organizationId
        );

        String dump = "/tmp/" + sourceDatabase + ".dump";
        assertExecOk(POSTGRES.execInContainer(
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file=" + dump,
            "--dbname=" + connectionUri(sourceDatabase)
        ));
        createDatabase(restoredDatabase);
        assertExecOk(POSTGRES.execInContainer(
            "pg_restore",
            "--no-owner",
            "--no-privileges",
            "--exit-on-error",
            "--dbname=" + connectionUri(restoredDatabase),
            dump
        ));

        JdbcTemplate restored = jdbc(databaseUrl(restoredDatabase), "public");
        assertThat(restored.queryForObject(
            "SELECT organization_name FROM organization WHERE organization_id = ?",
            String.class,
            organizationId
        )).isEqualTo("备份验证组织");
        assertThat(restored.queryForObject(
            "SELECT COUNT(*) FROM flyway_schema_history WHERE success",
            Integer.class
        )).isEqualTo(5);
        flyway(databaseUrl(restoredDatabase), "public", null).validate();
    }

    private static Fixture seedCapture(JdbcTemplate jdbc) {
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
        UUID detectionTaskId = UUID.randomUUID();
        UUID attemptId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO organization(
                organization_id, organization_code, organization_name, status
            ) VALUES (?, ?, '测试组织', 'ACTIVE')
            """,
            organizationId,
            "org-" + organizationId
        );
        jdbc.update(
            """
            INSERT INTO production_line(
                line_id, organization_id, line_code, line_name, status
            ) VALUES (?, ?, ?, '测试产线', 'ACTIVE')
            """,
            lineId,
            organizationId,
            "line-" + lineId
        );
        jdbc.update(
            """
            INSERT INTO capture_recipe(
                recipe_id, recipe_name, version, config,
                config_sha256, status
            ) VALUES (?, ?, '1', '{}'::jsonb, ?, 'APPROVED')
            """,
            recipeId,
            "recipe-" + recipeId,
            "a".repeat(64)
        );
        jdbc.update(
            """
            INSERT INTO station(
                station_id, line_id, station_code, station_name,
                active_recipe_id, status
            ) VALUES (?, ?, ?, '测试工位', ?, 'ACTIVE')
            """,
            stationId,
            lineId,
            "station-" + stationId,
            recipeId
        );
        jdbc.update(
            """
            INSERT INTO capture_event(
                capture_id, station_id, trigger_id, client_sequence,
                source_type, captured_at, recipe_id, status,
                quality_status, request_digest
            ) VALUES (?, ?, 'trigger-1', 1, 'ONLINE', now(), ?,
                'CREATED', 'OK', ?)
            """,
            captureId,
            stationId,
            recipeId,
            "f".repeat(64)
        );
        jdbc.update(
            "INSERT INTO dataset(dataset_id, dataset_name, purpose) VALUES (?, ?, '约束测试')",
            datasetId,
            "constraint-dataset-" + datasetId
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
            "constraint-model-" + modelId
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
            "4".repeat(64)
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
            "constraint-pipeline-" + pipelineId,
            modelVersionId,
            "5".repeat(64)
        );
        jdbc.update(
            """
            INSERT INTO detection_task(
                detection_task_id, capture_id, pipeline_id,
                purpose, status, priority
            ) VALUES (?, ?, ?, 'PRODUCTION', 'SUCCEEDED', 10)
            """,
            detectionTaskId,
            captureId,
            pipelineId
        );
        jdbc.update(
            """
            INSERT INTO detection_attempt(
                attempt_id, detection_task_id, attempt_no, worker_id,
                runtime_version, model_sha256, trace_id, status,
                started_at, finished_at
            ) VALUES (?, ?, 1, 'worker-1', '1', ?, ?, 'SUCCEEDED',
                now() - interval '1 second', now())
            """,
            attemptId,
            detectionTaskId,
            "4".repeat(64),
            "5".repeat(32)
        );
        return new Fixture(
            organizationId,
            lineId,
            recipeId,
            stationId,
            captureId,
            detectionTaskId,
            attemptId
        );
    }

    private static UUID insertImage(
            JdbcTemplate jdbc,
            UUID captureId,
            String objectKey) {
        UUID imageId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO image_object(
                image_id, capture_id, kind, bucket, object_key,
                sha256, size_bytes, media_type, state
            ) VALUES (?, ?, 'RAW', 'td-raw', ?, ?, 12, 'image/png', 'STAGING')
            """,
            imageId,
            captureId,
            objectKey,
            "a".repeat(64)
        );
        return imageId;
    }

    private static UUID seedDatasetVersion(JdbcTemplate jdbc) {
        UUID datasetId = UUID.randomUUID();
        UUID versionId = UUID.randomUUID();
        jdbc.update(
            "INSERT INTO dataset(dataset_id, dataset_name, purpose) VALUES (?, ?, '测试')",
            datasetId,
            "dataset-" + datasetId
        );
        jdbc.update(
            """
            INSERT INTO dataset_version(
                dataset_version_id, dataset_id, version, status
            ) VALUES (?, ?, '1', 'BUILDING')
            """,
            versionId,
            datasetId
        );
        return versionId;
    }

    private static void seedDetectionReaderScope(
            JdbcTemplate jdbc,
            String externalSubject,
            UUID stationId) {
        UUID userId = UUID.randomUUID();
        UUID roleId = UUID.randomUUID();
        UUID permissionId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO sys_user(
                user_id, external_subject, display_name, status
            ) VALUES (?, ?, '检测查询测试用户', 'ACTIVE')
            """,
            userId,
            externalSubject
        );
        jdbc.update(
            """
            INSERT INTO sys_role(role_id, role_code, role_name)
            VALUES (?, ?, '检测读取角色')
            """,
            roleId,
            "detection-reader-" + roleId
        );
        jdbc.update(
            """
            INSERT INTO sys_permission(
                permission_id, permission_code, description
            ) VALUES (?, 'detection:read', '读取授权范围内的检测')
            """,
            permissionId
        );
        jdbc.update(
            "INSERT INTO sys_user_role(user_id, role_id) VALUES (?, ?)",
            userId,
            roleId
        );
        jdbc.update(
            """
            INSERT INTO sys_role_permission(role_id, permission_id)
            VALUES (?, ?)
            """,
            roleId,
            permissionId
        );
        jdbc.update(
            """
            INSERT INTO sys_scope_binding(
                scope_binding_id, subject_type, subject_id,
                scope_type, scope_id
            ) VALUES (?, 'ROLE', ?, 'STATION', ?)
            """,
            UUID.randomUUID(),
            roleId,
            stationId
        );
    }

    private static UUID seedUser(
            JdbcTemplate jdbc,
            String externalSubject) {
        UUID userId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO sys_user(
                user_id, external_subject, display_name, status
            ) VALUES (?, ?, ?, 'ACTIVE')
            """,
            userId,
            externalSubject,
            "测试用户-" + externalSubject
        );
        return userId;
    }

    private static void seedScopedPermission(
            JdbcTemplate jdbc,
            List<String> externalSubjects,
            String permissionCode,
            UUID stationId) {
        UUID roleId = UUID.randomUUID();
        UUID permissionId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO sys_role(role_id, role_code, role_name)
            VALUES (?, ?, ?)
            """,
            roleId,
            permissionCode.replace(':', '-') + "-" + roleId,
            "测试范围角色-" + permissionCode
        );
        jdbc.update(
            """
            INSERT INTO sys_permission(
                permission_id, permission_code, description
            ) VALUES (?, ?, ?)
            ON CONFLICT (permission_code) DO NOTHING
            """,
            permissionId,
            permissionCode,
            "测试权限-" + permissionCode
        );
        UUID stablePermissionId = jdbc.queryForObject(
            """
            SELECT permission_id FROM sys_permission
            WHERE permission_code = ?
            """,
            UUID.class,
            permissionCode
        );
        jdbc.update(
            """
            INSERT INTO sys_role_permission(role_id, permission_id)
            VALUES (?, ?)
            """,
            roleId,
            stablePermissionId
        );
        for (String subject : externalSubjects) {
            UUID userId = jdbc.query(
                """
                SELECT user_id FROM sys_user WHERE external_subject = ?
                """,
                (row, index) -> row.getObject("user_id", UUID.class),
                subject
            ).stream().findFirst().orElseGet(() -> seedUser(jdbc, subject));
            jdbc.update(
                "INSERT INTO sys_user_role(user_id, role_id) VALUES (?, ?)",
                userId,
                roleId
            );
        }
        jdbc.update(
            """
            INSERT INTO sys_scope_binding(
                scope_binding_id, subject_type, subject_id,
                scope_type, scope_id
            ) VALUES (?, 'ROLE', ?, 'STATION', ?)
            """,
            UUID.randomUUID(),
            roleId,
            stationId
        );
    }

    private static void insertReviewRecord(
            JdbcTemplate jdbc,
            UUID reviewRecordId,
            UUID taskId,
            UUID reviewerId,
            String decision,
            String reasonCode,
            String comment) {
        jdbc.update(
            """
            INSERT INTO review_record(
                review_record_id, review_task_id, reviewer_id,
                decision, reason_code, comment, defect_type_codes,
                review_round, submitted_at, client_submitted_at,
                submission_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, '[]'::jsonb,
                1, now(), now(), ?)
            """,
            reviewRecordId,
            taskId,
            reviewerId,
            decision,
            reasonCode,
            comment,
            "b".repeat(64)
        );
    }

    private static int insertReviewDatasetSample(
            JdbcTemplate jdbc,
            UUID sampleId,
            UUID datasetVersionId,
            UUID captureId,
            UUID imageId,
            UUID reviewRecordId,
            String sampleKey) {
        return jdbc.update(
            """
            INSERT INTO dataset_sample(
                dataset_sample_id, dataset_version_id, sample_key,
                capture_id, image_id, label, split,
                source_review_record_id, content_sha256, group_key
            ) VALUES (?, ?, ?, ?, ?, 'PASS', 'TRAIN', ?, ?, 'review-group')
            """,
            sampleId,
            datasetVersionId,
            sampleKey,
            captureId,
            imageId,
            reviewRecordId,
            "c".repeat(64)
        );
    }

    private static Flyway flyway(
            String databaseUrl,
            String schema,
            MigrationVersion target) {
        var configuration = Flyway.configure()
            .dataSource(
                databaseUrl,
                POSTGRES.getUsername(),
                POSTGRES.getPassword()
            )
            .locations("classpath:db/migration")
            .schemas(schema)
            .defaultSchema(schema)
            .createSchemas(true)
            .validateMigrationNaming(true)
            .cleanDisabled(true);
        if (target != null) {
            configuration.target(target);
        }
        return configuration.load();
    }

    private static JdbcTemplate jdbc(String databaseUrl, String schema) {
        DriverManagerDataSource dataSource = new DriverManagerDataSource();
        dataSource.setDriverClassName("org.postgresql.Driver");
        dataSource.setUrl(withCurrentSchema(databaseUrl, schema));
        dataSource.setUsername(POSTGRES.getUsername());
        dataSource.setPassword(POSTGRES.getPassword());
        return new JdbcTemplate(dataSource);
    }

    private static String withCurrentSchema(String url, String schema) {
        return url + (url.contains("?") ? "&" : "?") + "currentSchema=" + schema;
    }

    private static String uniqueName(String prefix) {
        return prefix + "_" + UUID.randomUUID().toString().replace("-", "");
    }

    private static void createDatabase(String database) throws SQLException {
        try (
            Connection connection = DriverManager.getConnection(
                POSTGRES.getJdbcUrl(),
                POSTGRES.getUsername(),
                POSTGRES.getPassword()
            );
            Statement statement = connection.createStatement()
        ) {
            connection.setAutoCommit(true);
            statement.execute("CREATE DATABASE " + database);
        }
    }

    private static String databaseUrl(String database) {
        return "jdbc:postgresql://"
            + POSTGRES.getHost()
            + ":"
            + POSTGRES.getMappedPort(PostgreSQLContainer.POSTGRESQL_PORT)
            + "/"
            + database;
    }

    private static String connectionUri(String database) {
        return "postgresql://"
            + POSTGRES.getUsername()
            + ":"
            + POSTGRES.getPassword()
            + "@localhost:5432/"
            + database;
    }

    private static void assertExecOk(
            org.testcontainers.containers.Container.ExecResult result) {
        assertThat(result.getExitCode())
            .withFailMessage(
                "容器命令失败：%s%s",
                result.getStdout(),
                result.getStderr()
            )
            .isZero();
    }

    private record Fixture(
        UUID organizationId,
        UUID lineId,
        UUID recipeId,
        UUID stationId,
        UUID captureId,
        UUID detectionTaskId,
        UUID attemptId
    ) {
    }
}
