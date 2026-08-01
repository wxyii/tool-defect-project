package com.tooldefect.business.overview.infrastructure;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.overview.application.OverviewQueryRepository;

@Repository
public class JdbcOverviewQueryRepository implements OverviewQueryRepository {
    private static final String AUTHORIZED_STATIONS = """
        WITH actor_input AS (
            SELECT ?::text AS actor_id
        ), authorized_stations AS (
            SELECT DISTINCT station.station_id, station.status
            FROM station
            JOIN production_line line ON line.line_id = station.line_id
            CROSS JOIN actor_input actor
            WHERE EXISTS (
                SELECT 1
                FROM sys_user user_account
                JOIN sys_user_role user_role
                  ON user_role.user_id = user_account.user_id
                JOIN sys_role_permission role_permission
                  ON role_permission.role_id = user_role.role_id
                JOIN sys_permission permission
                  ON permission.permission_id = role_permission.permission_id
                JOIN sys_scope_binding scope_binding
                  ON (
                    scope_binding.subject_type = 'USER'
                    AND scope_binding.subject_id = user_account.user_id
                  ) OR (
                    scope_binding.subject_type = 'ROLE'
                    AND scope_binding.subject_id = user_role.role_id
                  )
                WHERE (
                    user_account.user_id::text = actor.actor_id
                    OR user_account.external_subject = actor.actor_id
                  )
                  AND user_account.status = 'ACTIVE'
                  AND permission.permission_code = 'detection:read'
                  AND (
                    scope_binding.scope_type = 'STATION'
                    AND scope_binding.scope_id = station.station_id
                    OR scope_binding.scope_type = 'LINE'
                    AND scope_binding.scope_id = station.line_id
                    OR scope_binding.scope_type = 'ORGANIZATION'
                    AND scope_binding.scope_id = line.organization_id
                  )
            )
        )
        """;

    private final JdbcTemplate jdbc;

    public JdbcOverviewQueryRepository(JdbcTemplate jdbc) {
        this.jdbc = Objects.requireNonNull(jdbc);
    }

    @Override
    public Map<String, Object> summarize(
            String actorId,
            Instant generatedAt,
            Instant currentStart,
            Instant currentEnd,
            Instant previousStart,
            Instant previousEnd,
            Instant heartbeatCutoff,
            long heartbeatFreshnessSeconds,
            String timezone) {
        Map<String, Object> capture = captureAndQuality(
            actorId, currentStart, currentEnd, previousStart, previousEnd
        );
        Map<String, Object> reviews = reviewBacklog(actorId, generatedAt);
        Map<String, Object> fleet = fleet(actorId, heartbeatCutoff);
        Map<String, Object> inference = inference(
            actorId, generatedAt, currentStart, currentEnd
        );
        Map<String, Object> runtime = modelRuntime(actorId);
        Map<String, Object> response = response(
            "generated_at", generatedAt.toString(),
            "window", response(
                "timezone", timezone,
                "current_start", currentStart.toString(),
                "current_end", currentEnd.toString(),
                "previous_start", previousStart.toString(),
                "previous_end", previousEnd.toString()
            ),
            "captures", response(
                "total", number(capture, "capture_total"),
                "pass", number(capture, "capture_pass"),
                "fail", number(capture, "capture_fail"),
                "hold", number(capture, "capture_hold"),
                "unresolved", number(capture, "capture_unresolved")
            ),
            "reviews", response(
                "total", number(reviews, "review_total"),
                "pending", number(reviews, "review_pending"),
                "claimed", number(reviews, "review_claimed"),
                "second_review_pending",
                    number(reviews, "review_second_pending"),
                "escalated", number(reviews, "review_escalated"),
                "oldest_age_seconds", number(reviews, "oldest_age_seconds")
            ),
            "fleet", response(
                "stations_total", number(fleet, "stations_total"),
                "stations_online", number(fleet, "stations_online"),
                "stations_maintenance", number(fleet, "stations_maintenance"),
                "devices_total", number(fleet, "devices_total"),
                "devices_online", number(fleet, "devices_online"),
                "devices_degraded", number(fleet, "devices_degraded"),
                "devices_offline", number(fleet, "devices_offline"),
                "heartbeat_freshness_seconds", heartbeatFreshnessSeconds
            ),
            "inference", response(
                "queued", number(inference, "queued"),
                "running", number(inference, "running"),
                "retry_wait", number(inference, "retry_wait"),
                "dead", number(inference, "dead"),
                "failures_24h", number(inference, "failures_24h"),
                "completed_in_window",
                    number(inference, "completed_in_window"),
                "p95_duration_ms", nullableNumber(inference, "p95_duration_ms")
            ),
            "model_runtime", runtime,
            "outcome_comparison", response(
                "current", response(
                    "qualified", number(capture, "current_qualified"),
                    "unqualified", number(capture, "current_unqualified"),
                    "inconclusive", number(capture, "current_inconclusive")
                ),
                "previous", response(
                    "qualified", number(capture, "previous_qualified"),
                    "unqualified", number(capture, "previous_unqualified"),
                    "inconclusive", number(capture, "previous_inconclusive")
                )
            ),
            "quality_comparison", response(
                "current", response(
                    "ok", number(capture, "current_quality_ok"),
                    "warning", number(capture, "current_quality_warning"),
                    "rejected", number(capture, "current_quality_rejected")
                ),
                "previous", response(
                    "ok", number(capture, "previous_quality_ok"),
                    "warning", number(capture, "previous_quality_warning"),
                    "rejected", number(capture, "previous_quality_rejected")
                )
            )
        );
        return Map.copyOf(response);
    }

    private Map<String, Object> captureAndQuality(
            String actorId,
            Instant currentStart,
            Instant currentEnd,
            Instant previousStart,
            Instant previousEnd) {
        return jdbc.queryForMap(
            AUTHORIZED_STATIONS + """
            , overview_window AS (
                SELECT ?::timestamptz AS current_start,
                       ?::timestamptz AS current_end,
                       ?::timestamptz AS previous_start,
                       ?::timestamptz AS previous_end
            ), scoped_captures AS (
                SELECT capture.capture_id,
                       capture.captured_at,
                       capture.current_disposition,
                       capture.quality_status
                FROM capture_event capture
                JOIN authorized_stations allowed
                  ON allowed.station_id = capture.station_id
                CROSS JOIN overview_window bounds
                WHERE capture.captured_at >= bounds.previous_start
                  AND capture.captured_at < bounds.current_end
            ), scoped_outcomes AS (
                SELECT capture.captured_at, result.algorithm_outcome
                FROM scoped_captures capture
                JOIN detection_task task
                  ON task.capture_id = capture.capture_id
                JOIN detection_result result
                  ON result.detection_task_id = task.detection_task_id
            )
            SELECT
                COUNT(*) FILTER (
                    WHERE captured_at >= bounds.current_start
                      AND captured_at < bounds.current_end
                ) AS capture_total,
                COUNT(*) FILTER (
                    WHERE captured_at >= bounds.current_start
                      AND captured_at < bounds.current_end
                      AND current_disposition = 'PASS'
                ) AS capture_pass,
                COUNT(*) FILTER (
                    WHERE captured_at >= bounds.current_start
                      AND captured_at < bounds.current_end
                      AND current_disposition = 'FAIL'
                ) AS capture_fail,
                COUNT(*) FILTER (
                    WHERE captured_at >= bounds.current_start
                      AND captured_at < bounds.current_end
                      AND current_disposition = 'HOLD'
                ) AS capture_hold,
                COUNT(*) FILTER (
                    WHERE captured_at >= bounds.current_start
                      AND captured_at < bounds.current_end
                      AND current_disposition IS NULL
                ) AS capture_unresolved,
                COUNT(*) FILTER (
                    WHERE captured_at >= bounds.current_start
                      AND captured_at < bounds.current_end
                      AND quality_status = 'OK'
                ) AS current_quality_ok,
                COUNT(*) FILTER (
                    WHERE captured_at >= bounds.current_start
                      AND captured_at < bounds.current_end
                      AND quality_status = 'QUALITY_WARNING'
                ) AS current_quality_warning,
                COUNT(*) FILTER (
                    WHERE captured_at >= bounds.current_start
                      AND captured_at < bounds.current_end
                      AND quality_status = 'QUALITY_REJECTED'
                ) AS current_quality_rejected,
                COUNT(*) FILTER (
                    WHERE captured_at >= bounds.previous_start
                      AND captured_at < bounds.previous_end
                      AND quality_status = 'OK'
                ) AS previous_quality_ok,
                COUNT(*) FILTER (
                    WHERE captured_at >= bounds.previous_start
                      AND captured_at < bounds.previous_end
                      AND quality_status = 'QUALITY_WARNING'
                ) AS previous_quality_warning,
                COUNT(*) FILTER (
                    WHERE captured_at >= bounds.previous_start
                      AND captured_at < bounds.previous_end
                      AND quality_status = 'QUALITY_REJECTED'
                ) AS previous_quality_rejected,
                (SELECT COUNT(*) FILTER (
                    WHERE captured_at >= bounds.current_start
                      AND captured_at < bounds.current_end
                      AND algorithm_outcome = 'QUALIFIED'
                ) FROM scoped_outcomes) AS current_qualified,
                (SELECT COUNT(*) FILTER (
                    WHERE captured_at >= bounds.current_start
                      AND captured_at < bounds.current_end
                      AND algorithm_outcome = 'UNQUALIFIED'
                ) FROM scoped_outcomes) AS current_unqualified,
                (SELECT COUNT(*) FILTER (
                    WHERE captured_at >= bounds.current_start
                      AND captured_at < bounds.current_end
                      AND algorithm_outcome = 'INCONCLUSIVE'
                ) FROM scoped_outcomes) AS current_inconclusive,
                (SELECT COUNT(*) FILTER (
                    WHERE captured_at >= bounds.previous_start
                      AND captured_at < bounds.previous_end
                      AND algorithm_outcome = 'QUALIFIED'
                ) FROM scoped_outcomes) AS previous_qualified,
                (SELECT COUNT(*) FILTER (
                    WHERE captured_at >= bounds.previous_start
                      AND captured_at < bounds.previous_end
                      AND algorithm_outcome = 'UNQUALIFIED'
                ) FROM scoped_outcomes) AS previous_unqualified,
                (SELECT COUNT(*) FILTER (
                    WHERE captured_at >= bounds.previous_start
                      AND captured_at < bounds.previous_end
                      AND algorithm_outcome = 'INCONCLUSIVE'
                ) FROM scoped_outcomes) AS previous_inconclusive
            FROM overview_window bounds
            LEFT JOIN scoped_captures ON TRUE
            GROUP BY bounds.current_start,
                     bounds.current_end,
                     bounds.previous_start,
                     bounds.previous_end
            """,
            actorId,
            Timestamp.from(currentStart),
            Timestamp.from(currentEnd),
            Timestamp.from(previousStart),
            Timestamp.from(previousEnd)
        );
    }

    private Map<String, Object> reviewBacklog(
            String actorId, Instant generatedAt) {
        return jdbc.queryForMap(
            AUTHORIZED_STATIONS + """
            , scoped_reviews AS (
                SELECT review.status, review.created_at
                FROM review_task review
                JOIN capture_event capture
                  ON capture.capture_id = review.capture_id
                JOIN authorized_stations allowed
                  ON allowed.station_id = capture.station_id
                WHERE review.status IN (
                    'PENDING', 'CLAIMED', 'SECOND_REVIEW_PENDING', 'ESCALATED'
                )
            )
            SELECT COUNT(*) AS review_total,
                   COUNT(*) FILTER (WHERE status = 'PENDING') AS review_pending,
                   COUNT(*) FILTER (WHERE status = 'CLAIMED') AS review_claimed,
                   COUNT(*) FILTER (
                       WHERE status = 'SECOND_REVIEW_PENDING'
                   ) AS review_second_pending,
                   COUNT(*) FILTER (
                       WHERE status = 'ESCALATED'
                   ) AS review_escalated,
                   COALESCE(GREATEST(
                       FLOOR(EXTRACT(EPOCH FROM (?::timestamptz - MIN(created_at)))),
                       0
                   ), 0)::bigint AS oldest_age_seconds
            FROM scoped_reviews
            """,
            actorId,
            Timestamp.from(generatedAt)
        );
    }

    private Map<String, Object> fleet(
            String actorId, Instant heartbeatCutoff) {
        return jdbc.queryForMap(
            AUTHORIZED_STATIONS + """
            , scoped_devices AS (
                SELECT device.station_id, device.status, device.last_seen_at
                FROM device
                JOIN authorized_stations allowed
                  ON allowed.station_id = device.station_id
            )
            SELECT
                (SELECT COUNT(*) FROM authorized_stations) AS stations_total,
                (SELECT COUNT(*)
                 FROM authorized_stations station
                 WHERE station.status = 'ACTIVE'
                   AND EXISTS (
                       SELECT 1 FROM scoped_devices device
                       WHERE device.station_id = station.station_id
                         AND device.status = 'ONLINE'
                         AND device.last_seen_at >= ?
                   )) AS stations_online,
                (SELECT COUNT(*) FROM authorized_stations
                 WHERE status = 'MAINTENANCE') AS stations_maintenance,
                COUNT(*) AS devices_total,
                COUNT(*) FILTER (
                    WHERE status = 'ONLINE' AND last_seen_at >= ?
                ) AS devices_online,
                COUNT(*) FILTER (
                    WHERE status = 'DEGRADED' AND last_seen_at >= ?
                ) AS devices_degraded,
                COUNT(*) FILTER (
                    WHERE last_seen_at IS NULL OR last_seen_at < ?
                       OR status NOT IN ('ONLINE', 'DEGRADED')
                ) AS devices_offline
            FROM scoped_devices
            """,
            actorId,
            Timestamp.from(heartbeatCutoff),
            Timestamp.from(heartbeatCutoff),
            Timestamp.from(heartbeatCutoff),
            Timestamp.from(heartbeatCutoff)
        );
    }

    private Map<String, Object> inference(
            String actorId,
            Instant generatedAt,
            Instant currentStart,
            Instant currentEnd) {
        return jdbc.queryForMap(
            AUTHORIZED_STATIONS + """
            , scoped_tasks AS (
                SELECT task.status,
                       task.started_at,
                       task.finished_at,
                       task.updated_at
                FROM detection_task task
                JOIN capture_event capture
                  ON capture.capture_id = task.capture_id
                JOIN authorized_stations allowed
                  ON allowed.station_id = capture.station_id
            )
            SELECT COUNT(*) FILTER (WHERE status = 'QUEUED') AS queued,
                   COUNT(*) FILTER (WHERE status = 'RUNNING') AS running,
                   COUNT(*) FILTER (WHERE status = 'RETRY_WAIT') AS retry_wait,
                   COUNT(*) FILTER (WHERE status = 'DEAD') AS dead,
                   COUNT(*) FILTER (
                       WHERE status = 'DEAD' AND updated_at >= ?
                   ) AS failures_24h,
                   COUNT(*) FILTER (
                       WHERE status = 'SUCCEEDED'
                         AND finished_at >= ? AND finished_at < ?
                   ) AS completed_in_window,
                   percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY EXTRACT(EPOCH FROM (finished_at - started_at)) * 1000
                   ) FILTER (
                       WHERE status = 'SUCCEEDED'
                         AND started_at IS NOT NULL
                         AND finished_at >= ? AND finished_at < ?
                   ) AS p95_duration_ms
            FROM scoped_tasks
            """,
            actorId,
            Timestamp.from(generatedAt.minusSeconds(86_400)),
            Timestamp.from(currentStart), Timestamp.from(currentEnd),
            Timestamp.from(currentStart), Timestamp.from(currentEnd)
        );
    }

    private Map<String, Object> modelRuntime(String actorId) {
        String scopedDeployments = AUTHORIZED_STATIONS + """
            , scoped_deployments AS (
                SELECT deployment.*
                FROM model_deployment deployment
                WHERE EXISTS (SELECT 1 FROM authorized_stations)
                  AND (
                    deployment.deployment_strategy = 'PERCENTAGE'
                    OR EXISTS (
                        SELECT 1
                        FROM authorized_stations station
                        WHERE jsonb_exists(
                            deployment.station_scope,
                            station.station_id::text
                        )
                    )
                  )
            )
            """;
        Map<String, Object> counts = jdbc.queryForMap(
            scopedDeployments + """
            SELECT COUNT(*) FILTER (
                       WHERE environment = 'SHADOW' AND status = 'ACTIVE'
                   ) AS active_shadow,
                   COUNT(*) FILTER (
                       WHERE environment = 'CANARY' AND status = 'ACTIVE'
                   ) AS active_canary,
                   LEAST(COALESCE(SUM(traffic_ratio) FILTER (
                       WHERE environment = 'CANARY' AND status = 'ACTIVE'
                   ), 0), 1) AS canary_ratio
            FROM scoped_deployments
            """,
            actorId
        );
        List<Map<String, Object>> productionRows = jdbc.query(
            scopedDeployments + """
            SELECT deployment.model_deployment_id,
                   deployment.model_version_id,
                   version.registry_name,
                   version.registry_version,
                   deployment.traffic_ratio,
                   deployment.effective_at
            FROM scoped_deployments deployment
            JOIN model_version version
              ON version.model_version_id = deployment.model_version_id
            WHERE deployment.environment = 'PRODUCTION'
              AND deployment.status = 'ACTIVE'
            ORDER BY deployment.effective_at DESC NULLS LAST,
                     deployment.created_at DESC,
                     deployment.model_deployment_id DESC
            LIMIT 1
            """,
            JdbcOverviewQueryRepository::production,
            actorId
        );
        return response(
            "production", productionRows.isEmpty() ? null : productionRows.getFirst(),
            "active_shadow_deployments", number(counts, "active_shadow"),
            "active_canary_deployments", number(counts, "active_canary"),
            "canary_traffic_ratio", decimal(counts, "canary_ratio")
        );
    }

    private static Map<String, Object> production(ResultSet row, int index)
            throws SQLException {
        Timestamp effective = row.getTimestamp("effective_at");
        return response(
            "deployment_id",
                row.getObject("model_deployment_id").toString(),
            "model_version_id",
                row.getObject("model_version_id").toString(),
            "registry_name", row.getString("registry_name"),
            "registry_version", row.getString("registry_version"),
            "traffic_ratio", row.getBigDecimal("traffic_ratio").doubleValue(),
            "effective_at", effective == null ? null : effective.toInstant().toString()
        );
    }

    private static long number(Map<String, Object> row, String key) {
        Object value = row.get(key);
        if (!(value instanceof Number number)) {
            throw new IllegalStateException("总览 SQL 缺少数值字段：" + key);
        }
        return number.longValue();
    }

    private static double decimal(Map<String, Object> row, String key) {
        Object value = row.get(key);
        if (!(value instanceof Number number)) {
            throw new IllegalStateException("总览 SQL 缺少数字字段：" + key);
        }
        return number.doubleValue();
    }

    private static Double nullableNumber(Map<String, Object> row, String key) {
        Object value = row.get(key);
        return value == null ? null : decimal(row, key);
    }

    private static Map<String, Object> response(Object... pairs) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index < pairs.length; index += 2) {
            result.put(String.valueOf(pairs[index]), pairs[index + 1]);
        }
        return result;
    }
}
