package com.tooldefect.business.detectionbatch.infrastructure;

import com.tooldefect.business.detectionbatch.application.R2DataRepository;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.util.Objects;

@Repository
public class JdbcR2DataRepository implements R2DataRepository {
    private final JdbcTemplate jdbc;

    public JdbcR2DataRepository(JdbcTemplate jdbc) {
        this.jdbc = Objects.requireNonNull(jdbc);
    }

    @Override
    public BackfillResult backfillLegacyCaptures() {
        return jdbc.queryForObject(
            "SELECT * FROM td_backfill_legacy_captures_v2()",
            (row, number) -> new BackfillResult(
                row.getInt("inserted_batches"),
                row.getInt("inserted_items"),
                row.getInt("held_captures")
            )
        );
    }

    @Override
    public int captureShadowDifferences() {
        Integer value = jdbc.queryForObject(
            "SELECT td_capture_shadow_differences_v2()", Integer.class
        );
        return value == null ? 0 : value;
    }

    @Override
    public ShadowSummary shadowSummary() {
        return jdbc.queryForObject(
            """
            SELECT
                (SELECT count(*) FROM r2_shadow_read_difference
                 WHERE status = 'HOLD') AS unexplained_differences,
                (SELECT count(*) FROM r2_migration_failure
                 WHERE status = 'HOLD') AS held_migrations
            """,
            (row, number) -> new ShadowSummary(
                row.getInt("unexplained_differences"),
                row.getInt("held_migrations")
            )
        );
    }
}
