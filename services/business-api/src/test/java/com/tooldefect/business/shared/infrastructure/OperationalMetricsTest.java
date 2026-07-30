package com.tooldefect.business.shared.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayDeque;
import java.util.Queue;

import org.junit.jupiter.api.Test;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;

final class OperationalMetricsTest {
    @Test
    void exportsDatabaseQueueStorageReviewDatasetModelAndBackupMetrics() {
        var meters = new SimpleMeterRegistry();
        var jdbc = new FakeJdbc(
            30L,
            2L,
            3L,
            4L,
            40L,
            6L,
            7L,
            5L,
            2L,
            1L,
            3L,
            1L,
            1_722_000_000L
        );
        var beans = new DefaultListableBeanFactory();
        var metrics = new OperationalMetrics(
            jdbc,
            meters,
            Clock.fixed(
                Instant.parse("2026-07-30T08:00:00Z"),
                ZoneOffset.UTC
            ),
            beans.getBeanProvider(RabbitTemplate.class),
            false
        );

        metrics.refresh();

        assertThat(value(meters, "tool.defect.database.writable"))
            .isEqualTo(1);
        assertThat(value(
            meters,
            "tool.defect.outbox.oldest.event.age.seconds"
        )).isEqualTo(30);
        assertThat(value(
            meters,
            "tool.defect.queue.dead.letter.messages"
        )).isEqualTo(2);
        assertThat(value(
            meters,
            "tool.defect.storage.orphan.objects"
        )).isEqualTo(3);
        assertThat(value(meters, "tool.defect.integrity.conflicts"))
            .isEqualTo(4);
        assertThat(value(
            meters,
            "tool.defect.review.oldest.task.age.seconds"
        )).isEqualTo(40);
        assertThat(value(meters, "tool.defect.review.pending.tasks"))
            .isEqualTo(6);
        assertThat(value(
            meters,
            "tool.defect.quality.reviewed.samples.30d"
        )).isEqualTo(7);
        assertThat(value(meters, "tool.defect.dataset.candidates"))
            .isEqualTo(5);
        assertThat(value(meters, "tool.defect.training.active.runs"))
            .isEqualTo(2);
        assertThat(value(
            meters,
            "tool.defect.training.failed.runs.30d"
        )).isEqualTo(1);
        assertThat(value(
            meters,
            "tool.defect.model.approval.candidates"
        )).isEqualTo(3);
        assertThat(value(
            meters,
            "tool.defect.model.production.deployments"
        )).isEqualTo(1);
        assertThat(value(
            meters,
            "tool.defect.backup.last.success.timestamp.seconds"
        )).isEqualTo(1_722_000_000L);
        assertThat(meters.getMeters()).allSatisfy(
            meter -> assertThat(meter.getId().getTags()).isEmpty()
        );
    }

    @Test
    void writeProbeFailureSetsDatabaseMetricToZero() {
        var meters = new SimpleMeterRegistry();
        var beans = new DefaultListableBeanFactory();
        var metrics = new OperationalMetrics(
            new FailingJdbc(),
            meters,
            Clock.systemUTC(),
            beans.getBeanProvider(RabbitTemplate.class),
            false
        );

        metrics.refresh();

        assertThat(value(meters, "tool.defect.database.writable"))
            .isZero();
    }

    private static long value(SimpleMeterRegistry meters, String name) {
        return Math.round(meters.get(name).gauge().value());
    }

    private static final class FakeJdbc extends JdbcTemplate {
        private final Queue<Long> values;

        FakeJdbc(Long... values) {
            this.values = new ArrayDeque<>(java.util.List.of(values));
        }

        @Override
        public int update(String sql, Object... args) {
            return 1;
        }

        @Override
        public <T> T queryForObject(String sql, Class<T> requiredType) {
            return requiredType.cast(values.remove());
        }
    }

    private static final class FailingJdbc extends JdbcTemplate {
        @Override
        public int update(String sql, Object... args) {
            throw new DataAccessResourceFailureException("unwritable");
        }
    }
}
