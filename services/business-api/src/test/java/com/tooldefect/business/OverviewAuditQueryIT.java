package com.tooldefect.business;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

import com.tooldefect.business.audit.domain.AuditRecord;
import com.tooldefect.business.audit.infrastructure.JdbcAuditQueryRepository;
import com.tooldefect.business.audit.infrastructure.JdbcAuditTrail;
import com.tooldefect.business.overview.infrastructure.JdbcOverviewQueryRepository;

/** 在真实 PostgreSQL 上执行总览聚合、范围约束、审计写入和游标分页。 */
@Testcontainers(disabledWithoutDocker = false)
class OverviewAuditQueryIT {
    @Container
    static final PostgreSQLContainer POSTGRES = new PostgreSQLContainer(
        DockerImageName.parse("postgres:18.4-alpine")
    )
        .withDatabaseName("tool_defect_overview_audit")
        .withUsername("tool_defect_test")
        .withPassword("tool-defect-test-only");

    @Test
    void overviewIsScopeBoundAndAuditQueryUsesStableCursor() {
        String schema = "overview_audit_"
            + UUID.randomUUID().toString().replace("-", "");
        Flyway.configure()
            .dataSource(
                POSTGRES.getJdbcUrl(),
                POSTGRES.getUsername(),
                POSTGRES.getPassword()
            )
            .locations("classpath:db/migration")
            .schemas(schema)
            .defaultSchema(schema)
            .createSchemas(true)
            .validateMigrationNaming(true)
            .cleanDisabled(true)
            .load()
            .migrate();
        JdbcTemplate jdbc = jdbc(schema);
        Instant now = Instant.parse("2026-08-01T05:00:00Z");
        UUID actorId = seedOverview(jdbc, now);

        Map<String, Object> overview = new JdbcOverviewQueryRepository(jdbc)
            .summarize(
                actorId.toString(),
                now,
                Instant.parse("2026-08-01T00:00:00Z"),
                now,
                Instant.parse("2026-07-31T00:00:00Z"),
                Instant.parse("2026-07-31T05:00:00Z"),
                Instant.parse("2026-08-01T04:58:00Z"),
                120,
                "Asia/Shanghai"
            );

        assertThat(section(overview, "captures"))
            .containsEntry("total", 1L)
            .containsEntry("unresolved", 1L);
        assertThat(section(overview, "reviews"))
            .containsEntry("pending", 1L)
            .containsEntry("oldest_age_seconds", 7_200L);
        assertThat(section(overview, "fleet"))
            .containsEntry("stations_total", 1L)
            .containsEntry("stations_online", 1L)
            .containsEntry("devices_online", 1L);
        assertThat(section(overview, "inference"))
            .containsEntry("queued", 0L)
            .containsEntry("p95_duration_ms", null);
        assertThat(section(overview, "model_runtime"))
            .containsEntry("production", null);

        JdbcAuditTrail trail = new JdbcAuditTrail(jdbc);
        trail.append(record(
            UUID.fromString("019f0000-0000-7000-8000-000000000011"),
            now.minusSeconds(20),
            "review.task.read"
        ));
        trail.append(record(
            UUID.fromString("019f0000-0000-7000-8000-000000000012"),
            now.minusSeconds(10),
            "audit.records.query"
        ));
        JdbcAuditQueryRepository audit = new JdbcAuditQueryRepository(jdbc);
        Map<String, Object> first = audit.list(
            now.minusSeconds(60), now, null, 1,
            "auditor", null, null, null, "SUCCESS"
        );
        assertThat(first).containsEntry("has_more", true);
        assertThat(items(first)).singleElement().satisfies(item -> {
            assertThat(item)
                .containsEntry("action", "audit.records.query")
                .containsEntry("actor_ip", "127.0.0.1");
        });

        Map<String, Object> second = audit.list(
            now.minusSeconds(60),
            now,
            String.valueOf(first.get("next_cursor")),
            1,
            "auditor",
            null,
            null,
            null,
            "SUCCESS"
        );
        assertThat(second).containsEntry("has_more", false);
        assertThat(items(second)).singleElement().satisfies(item ->
            assertThat(item).containsEntry("action", "review.task.read")
        );
    }

    private static UUID seedOverview(JdbcTemplate jdbc, Instant now) {
        UUID organizationId = UUID.randomUUID();
        UUID lineId = UUID.randomUUID();
        UUID recipeId = UUID.randomUUID();
        UUID stationId = UUID.randomUUID();
        UUID deviceId = UUID.randomUUID();
        UUID captureId = UUID.randomUUID();
        UUID reviewTaskId = UUID.randomUUID();
        UUID actorId = UUID.randomUUID();
        jdbc.update("""
            INSERT INTO organization(
                organization_id, organization_code, organization_name, status
            ) VALUES (?, ?, '总览测试组织', 'ACTIVE')
            """, organizationId, "overview-" + organizationId);
        jdbc.update("""
            INSERT INTO production_line(
                line_id, organization_id, line_code, line_name, status
            ) VALUES (?, ?, ?, '总览测试产线', 'ACTIVE')
            """, lineId, organizationId, "overview-" + lineId);
        jdbc.update("""
            INSERT INTO capture_recipe(
                recipe_id, recipe_name, version, config, config_sha256, status
            ) VALUES (?, ?, '1', '{}'::jsonb, ?, 'APPROVED')
            """, recipeId, "overview-" + recipeId, "a".repeat(64));
        jdbc.update("""
            INSERT INTO station(
                station_id, line_id, station_code, station_name,
                active_recipe_id, status
            ) VALUES (?, ?, ?, '总览测试工位', ?, 'ACTIVE')
            """, stationId, lineId, "overview-" + stationId, recipeId);
        jdbc.update("""
            INSERT INTO device(
                device_id, station_id, device_type, last_seen_at, status
            ) VALUES (?, ?, 'CAMERA', ?, 'ONLINE')
            """, deviceId, stationId, java.sql.Timestamp.from(now.minusSeconds(30)));
        jdbc.update("""
            INSERT INTO capture_event(
                capture_id, station_id, trigger_id, client_sequence,
                source_type, captured_at, recipe_id, status,
                quality_status, request_digest
            ) VALUES (?, ?, 'overview-trigger', 1, 'ONLINE', ?, ?,
                'PROCESSING', 'OK', ?)
            """,
            captureId,
            stationId,
            java.sql.Timestamp.from(now.minusSeconds(3_600)),
            recipeId,
            "b".repeat(64));
        jdbc.update("""
            INSERT INTO review_task(
                review_task_id, capture_id, priority, status,
                trigger_reasons, created_at, updated_at
            ) VALUES (?, ?, 10, 'PENDING', '["INCONCLUSIVE"]'::jsonb, ?, ?)
            """,
            reviewTaskId,
            captureId,
            java.sql.Timestamp.from(now.minusSeconds(7_200)),
            java.sql.Timestamp.from(now.minusSeconds(7_200)));
        jdbc.update("""
            INSERT INTO sys_user(
                user_id, external_subject, username, display_name,
                status, password_change_required, person_role
            ) VALUES (?, ?, ?, '总览测试用户', 'ACTIVE', false,
                'PRODUCTION_EMPLOYEE')
            """, actorId, actorId.toString(), "overview-" + actorId);
        UUID roleId = jdbc.queryForObject(
            "SELECT role_id FROM sys_role WHERE role_code = 'PRODUCTION_EMPLOYEE'",
            UUID.class
        );
        jdbc.update(
            "INSERT INTO sys_user_role(user_id, role_id) VALUES (?, ?)",
            actorId,
            roleId
        );
        jdbc.update("""
            INSERT INTO sys_scope_binding(
                scope_binding_id, subject_type, subject_id,
                scope_type, scope_id
            ) VALUES (?, 'ROLE', ?, 'ORGANIZATION', ?)
            """, UUID.randomUUID(), roleId, organizationId);
        return actorId;
    }

    private static AuditRecord record(
            UUID auditId, Instant occurredAt, String action) {
        return new AuditRecord(
            auditId,
            occurredAt,
            "USER",
            "auditor-user",
            "127.0.0.1",
            action,
            "audit_log",
            auditId.toString(),
            null,
            "c".repeat(64),
            "集成查询测试",
            "request-" + auditId,
            "d".repeat(32),
            "SUCCESS",
            null
        );
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> section(
            Map<String, Object> response, String name) {
        return (Map<String, Object>) response.get(name);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> items(Map<String, Object> page) {
        return (List<Map<String, Object>>) page.get("items");
    }

    private static JdbcTemplate jdbc(String schema) {
        DriverManagerDataSource dataSource = new DriverManagerDataSource();
        dataSource.setDriverClassName("org.postgresql.Driver");
        String url = POSTGRES.getJdbcUrl();
        dataSource.setUrl(
            url + (url.contains("?") ? "&" : "?") + "currentSchema=" + schema
        );
        dataSource.setUsername(POSTGRES.getUsername());
        dataSource.setPassword(POSTGRES.getPassword());
        return new JdbcTemplate(dataSource);
    }
}
