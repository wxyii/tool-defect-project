package com.tooldefect.business.quality.infrastructure;

import com.tooldefect.business.quality.application.QualityMetricsRepository;
import com.tooldefect.business.quality.domain.QualityMetrics;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

@Repository
public class JdbcQualityMetricsRepository implements QualityMetricsRepository {

    private static final String SCOPE_CTE = """
        WITH parameters AS (
            SELECT ?::timestamptz AS window_start,
                   ?::timestamptz AS window_end,
                   ?::uuid AS model_version_id
        ), scope AS (
            SELECT c.capture_id,
                   auto_disposition.disposition AS auto_disposition,
                   reviewed_disposition.disposition AS review_disposition,
                   reviewed_disposition.reason_code AS review_reason
            FROM capture_event c
            CROSS JOIN parameters p
            LEFT JOIN LATERAL (
                SELECT d.disposition
                FROM disposition_record d
                WHERE d.capture_id = c.capture_id
                  AND d.source = 'AUTO'
                ORDER BY d.created_at DESC, d.disposition_id DESC
                LIMIT 1
            ) auto_disposition ON TRUE
            LEFT JOIN LATERAL (
                SELECT d.disposition, rr.reason_code
                FROM disposition_record d
                JOIN review_record rr ON rr.review_record_id = d.review_record_id
                WHERE d.capture_id = c.capture_id
                  AND d.source IN ('REVIEW', 'SUPERVISOR_OVERRIDE')
                ORDER BY d.created_at DESC, d.disposition_id DESC
                LIMIT 1
            ) reviewed_disposition ON TRUE
            WHERE c.captured_at >= p.window_start
              AND c.captured_at < p.window_end
              AND (
                  p.model_version_id IS NULL
                  OR EXISTS (
                      SELECT 1
                      FROM detection_task dt
                      JOIN pipeline_version pv ON pv.pipeline_id = dt.pipeline_id
                      WHERE dt.capture_id = c.capture_id
                        AND pv.model_version_id = p.model_version_id
                  )
              )
        )
        """;

    private final JdbcTemplate jdbc;

    public JdbcQualityMetricsRepository(JdbcTemplate jdbc) {
        this.jdbc = Objects.requireNonNull(jdbc);
    }

    @Override
    public QualityMetrics summarize(Instant windowStart, Instant windowEnd, UUID modelVersionId) {
        Map<String, Object> totals = jdbc.queryForMap(
            SCOPE_CTE + """
            SELECT COUNT(*) AS total_sample_count,
                   COUNT(*) FILTER (
                       WHERE auto_disposition = 'PASS'
                   ) AS auto_pass_count,
                   COUNT(*) FILTER (
                       WHERE auto_disposition = 'PASS'
                         AND review_disposition = 'FAIL'
                   ) AS missed_detection_count,
                   COUNT(*) FILTER (
                       WHERE auto_disposition = 'FAIL'
                         AND review_disposition = 'PASS'
                   ) AS false_positive_count,
                   COUNT(*) FILTER (
                       WHERE auto_disposition IS NOT NULL
                         AND review_disposition IS NOT NULL
                         AND auto_disposition <> review_disposition
                   ) AS overturned_count,
                   COUNT(*) FILTER (
                       WHERE review_disposition IS NOT NULL
                   ) AS reviewed_count
            FROM scope
            """,
            Timestamp.from(windowStart), Timestamp.from(windowEnd), modelVersionId
        );
        long total = number(totals, "total_sample_count");
        long autoPass = number(totals, "auto_pass_count");
        long missed = number(totals, "missed_detection_count");
        long falsePositive = number(totals, "false_positive_count");
        long overturned = number(totals, "overturned_count");
        long reviewed = number(totals, "reviewed_count");
        List<QualityMetrics.Reason> reasons = reasons(windowStart, windowEnd, modelVersionId, reviewed);
        return new QualityMetrics(
            windowStart,
            windowEnd,
            autoPass == 0 ? 0.0 : (double) missed / autoPass,
            reviewed == 0 ? 0.0 : (double) overturned / reviewed,
            missed,
            falsePositive,
            reasons,
            total,
            total > 0 && reviewed == total
        );
    }

    private List<QualityMetrics.Reason> reasons(
            Instant windowStart, Instant windowEnd, UUID modelVersionId, long reviewed) {
        List<Map<String, Object>> rows = jdbc.queryForList(
            SCOPE_CTE + """
            SELECT review_reason AS reason, COUNT(*) AS count
            FROM scope
            WHERE review_reason IS NOT NULL
            GROUP BY review_reason
            ORDER BY count DESC, review_reason
            LIMIT 256
            """,
            Timestamp.from(windowStart), Timestamp.from(windowEnd), modelVersionId
        );
        List<QualityMetrics.Reason> result = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            long count = number(row, "count");
            result.add(new QualityMetrics.Reason(
                String.valueOf(row.get("reason")),
                count,
                reviewed == 0 ? 0.0 : (double) count / reviewed
            ));
        }
        return List.copyOf(result);
    }

    private static long number(Map<String, Object> row, String key) {
        Object value = row.get(key);
        if (!(value instanceof Number number)) {
            throw new IllegalStateException("质量指标 SQL 缺少数值字段: " + key);
        }
        return number.longValue();
    }
}
