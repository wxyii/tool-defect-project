package com.tooldefect.business.shared.infrastructure;

import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.Objects;
import java.util.concurrent.atomic.AtomicLong;

import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import io.micrometer.core.instrument.MeterRegistry;

/**
 * 低基数运行指标。所有量均来自技术投影或聚合查询，不把任务、人员、对象键
 * 或错误全文作为标签。数据库探针执行真实 UPDATE，读取成功不能冒充可写。
 */
@Component
public class OperationalMetrics {
    private final JdbcTemplate jdbc;
    private final RabbitTemplate rabbit;
    private final Clock clock;
    private final boolean messagingEnabled;
    private final AtomicLong databaseWritable = new AtomicLong();
    private final AtomicLong outboxOldestAgeSeconds = new AtomicLong();
    private final AtomicLong deadLetterMessages = new AtomicLong();
    private final AtomicLong readyMessages = new AtomicLong();
    private final AtomicLong storageOrphanObjects = new AtomicLong();
    private final AtomicLong integrityConflicts = new AtomicLong();
    private final AtomicLong reviewOldestAgeSeconds = new AtomicLong();
    private final AtomicLong reviewPendingTasks = new AtomicLong();
    private final AtomicLong qualityReviewedSamples30d = new AtomicLong();
    private final AtomicLong datasetCandidates = new AtomicLong();
    private final AtomicLong trainingActiveRuns = new AtomicLong();
    private final AtomicLong trainingFailedRuns30d = new AtomicLong();
    private final AtomicLong modelApprovalCandidates = new AtomicLong();
    private final AtomicLong productionModelDeployments = new AtomicLong();
    private final AtomicLong backupLastSuccessTimestamp = new AtomicLong();

    public OperationalMetrics(
            JdbcTemplate jdbc,
            MeterRegistry meters,
            Clock clock,
            ObjectProvider<RabbitTemplate> rabbitProvider,
            @Value("${td.messaging.enabled:false}") boolean messagingEnabled) {
        this.jdbc = Objects.requireNonNull(jdbc);
        this.clock = Objects.requireNonNull(clock);
        this.rabbit = rabbitProvider.getIfAvailable();
        this.messagingEnabled = messagingEnabled;
        gauge(meters, "tool.defect.database.writable", databaseWritable);
        gauge(
            meters,
            "tool.defect.outbox.oldest.event.age.seconds",
            outboxOldestAgeSeconds
        );
        gauge(
            meters,
            "tool.defect.queue.dead.letter.messages",
            deadLetterMessages
        );
        gauge(meters, "tool.defect.queue.ready.messages", readyMessages);
        gauge(
            meters,
            "tool.defect.storage.orphan.objects",
            storageOrphanObjects
        );
        gauge(
            meters,
            "tool.defect.integrity.conflicts",
            integrityConflicts
        );
        gauge(
            meters,
            "tool.defect.review.oldest.task.age.seconds",
            reviewOldestAgeSeconds
        );
        gauge(
            meters,
            "tool.defect.review.pending.tasks",
            reviewPendingTasks
        );
        gauge(
            meters,
            "tool.defect.quality.reviewed.samples.30d",
            qualityReviewedSamples30d
        );
        gauge(
            meters,
            "tool.defect.dataset.candidates",
            datasetCandidates
        );
        gauge(
            meters,
            "tool.defect.training.active.runs",
            trainingActiveRuns
        );
        gauge(
            meters,
            "tool.defect.training.failed.runs.30d",
            trainingFailedRuns30d
        );
        gauge(
            meters,
            "tool.defect.model.approval.candidates",
            modelApprovalCandidates
        );
        gauge(
            meters,
            "tool.defect.model.production.deployments",
            productionModelDeployments
        );
        gauge(
            meters,
            "tool.defect.backup.last.success.timestamp.seconds",
            backupLastSuccessTimestamp
        );
    }

    @Scheduled(
        fixedDelayString = "${td.telemetry.operational-metrics-delay:15000}"
    )
    void refresh() {
        Instant now = clock.instant();
        try {
            int changed = jdbc.update(
                """
                UPDATE operational_write_probe
                SET probed_at = ?
                WHERE probe_key = 1
                """,
                Timestamp.from(now)
            );
            databaseWritable.set(changed == 1 ? 1 : 0);
            outboxOldestAgeSeconds.set(queryLong("""
                SELECT COALESCE(
                    EXTRACT(EPOCH FROM now() - MIN(created_at))::bigint,
                    0
                )
                FROM outbox_event
                WHERE status IN ('NEW', 'CLAIMED', 'FAILED', 'DEAD')
                """));
            long databaseDead = queryLong("""
                SELECT COUNT(*)
                FROM outbox_event
                WHERE status = 'DEAD'
                """);
            deadLetterMessages.set(
                databaseDead + brokerDeadLetterMessages()
            );
            readyMessages.set(brokerReadyMessages());
            storageOrphanObjects.set(queryLong("""
                SELECT COUNT(*)
                FROM reliability_issue
                WHERE issue_type = 'STAGING_OBJECT_ORPHANED'
                """));
            integrityConflicts.set(queryLong("""
                SELECT COUNT(*)
                FROM reliability_issue
                WHERE issue_type IN (
                    'AVAILABLE_OBJECT_MISSING',
                    'OBJECT_INTEGRITY_MISMATCH'
                )
                """));
            reviewOldestAgeSeconds.set(queryLong("""
                SELECT COALESCE(
                    EXTRACT(EPOCH FROM now() - MIN(created_at))::bigint,
                    0
                )
                FROM review_task
                WHERE status IN (
                    'PENDING',
                    'CLAIMED',
                    'SECOND_PENDING'
                )
                """));
            reviewPendingTasks.set(queryLong("""
                SELECT COUNT(*)
                FROM review_task
                WHERE status IN ('PENDING', 'CLAIMED', 'SECOND_PENDING')
                """));
            qualityReviewedSamples30d.set(queryLong("""
                SELECT COUNT(*)
                FROM review_record
                WHERE submitted_at >= now() - interval '30 days'
                """));
            datasetCandidates.set(queryLong("""
                SELECT COUNT(*)
                FROM dataset_version
                WHERE status IN ('BUILDING', 'VALIDATING')
                """));
            trainingActiveRuns.set(queryLong("""
                SELECT COUNT(*)
                FROM training_run
                WHERE status IN ('QUEUED', 'RUNNING')
                """));
            trainingFailedRuns30d.set(queryLong("""
                SELECT COUNT(*)
                FROM training_run
                WHERE status = 'FAILED'
                  AND created_at >= now() - interval '30 days'
                """));
            modelApprovalCandidates.set(queryLong("""
                SELECT COUNT(*)
                FROM model_version
                WHERE approval_state IN ('CANDIDATE', 'VALIDATED')
                """));
            productionModelDeployments.set(queryLong("""
                SELECT COUNT(*)
                FROM model_deployment
                WHERE environment = 'PRODUCTION'
                  AND status = 'ACTIVE'
                """));
            backupLastSuccessTimestamp.set(queryLong("""
                SELECT COALESCE(
                    EXTRACT(EPOCH FROM MAX(finished_at))::bigint,
                    0
                )
                FROM recovery_drill
                WHERE result = 'SUCCEEDED'
                """));
        } catch (DataAccessException unavailable) {
            databaseWritable.set(0);
        }
    }

    private long queryLong(String sql) {
        Long value = jdbc.queryForObject(sql, Long.class);
        return value == null ? 0L : Math.max(0L, value);
    }

    private long brokerDeadLetterMessages() {
        if (!messagingEnabled || rabbit == null) {
            return 0;
        }
        Long value = rabbit.execute(
            channel -> channel.messageCount(RabbitTopology.DEAD_QUEUE)
        );
        return value == null ? 0 : Math.max(0, value);
    }

    private long brokerReadyMessages() {
        if (!messagingEnabled || rabbit == null) {
            return 0;
        }
        long total = 0;
        for (String queue : new String[] {
            RabbitTopology.PRODUCTION_GPU_QUEUE,
            RabbitTopology.PRODUCTION_CPU_QUEUE,
            RabbitTopology.SHADOW_GPU_QUEUE,
            RabbitTopology.BATCH_QUEUE
        }) {
            Long value = rabbit.execute(
                channel -> channel.messageCount(queue)
            );
            total += value == null ? 0 : Math.max(0, value);
        }
        return total;
    }

    private static void gauge(
            MeterRegistry meters,
            String name,
            AtomicLong value) {
        Objects.requireNonNull(meters).gauge(name, value);
    }
}
