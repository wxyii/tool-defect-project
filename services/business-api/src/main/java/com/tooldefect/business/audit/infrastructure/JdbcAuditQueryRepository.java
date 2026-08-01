package com.tooldefect.business.audit.infrastructure;

import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.audit.application.AuditQueryRepository;
import com.tooldefect.business.shared.api.ContractValues;

@Repository
public class JdbcAuditQueryRepository implements AuditQueryRepository {
    private final JdbcTemplate jdbc;

    public JdbcAuditQueryRepository(JdbcTemplate jdbc) {
        this.jdbc = Objects.requireNonNull(jdbc);
    }

    @Override
    public Map<String, Object> list(
            Instant startTime,
            Instant endTime,
            String cursor,
            int pageSize,
            String actorId,
            String action,
            String resourceType,
            String resourceId,
            String result) {
        Cursor boundary = cursor == null ? null : decode(cursor);
        StringBuilder sql = new StringBuilder("""
            SELECT audit_id,
                   occurred_at,
                   actor_type,
                   actor_id,
                   actor_ip,
                   action,
                   resource_type,
                   resource_id,
                   before_digest,
                   after_digest,
                   reason,
                   request_id,
                   trace_id,
                   result,
                   error_code
            FROM audit_log
            WHERE occurred_at >= ?
              AND occurred_at < ?
            """);
        List<Object> arguments = new ArrayList<>();
        arguments.add(Timestamp.from(startTime));
        arguments.add(Timestamp.from(endTime));
        appendContains(sql, arguments, "actor_id", actorId);
        appendContains(sql, arguments, "action", action);
        appendExact(sql, arguments, "resource_type", resourceType);
        appendContains(sql, arguments, "resource_id", resourceId);
        appendExact(sql, arguments, "result", result);
        if (boundary != null) {
            sql.append(" AND (occurred_at, audit_id) < (?, ?)");
            arguments.add(Timestamp.from(boundary.occurredAt()));
            arguments.add(boundary.auditId());
        }
        sql.append(" ORDER BY occurred_at DESC, audit_id DESC LIMIT ?");
        arguments.add(pageSize + 1);
        List<Row> rows = jdbc.query(
            sql.toString(),
            JdbcAuditQueryRepository::row,
            arguments.toArray()
        );
        boolean hasMore = rows.size() > pageSize;
        if (hasMore) {
            rows = new ArrayList<>(rows.subList(0, pageSize));
        }
        List<Map<String, Object>> items = rows.stream()
            .map(Row::response)
            .toList();
        String nextCursor = hasMore && !rows.isEmpty()
            ? encode(rows.getLast())
            : null;
        return response(
            "items", items,
            "next_cursor", nextCursor,
            "has_more", hasMore
        );
    }

    private static void appendContains(
            StringBuilder sql,
            List<Object> arguments,
            String column,
            String value) {
        if (value != null) {
            sql.append(" AND LOWER(").append(column)
                .append(") LIKE ? ESCAPE '!'");
            arguments.add("%" + escape(value.toLowerCase(java.util.Locale.ROOT)) + "%");
        }
    }

    private static void appendExact(
            StringBuilder sql,
            List<Object> arguments,
            String column,
            String value) {
        if (value != null) {
            sql.append(" AND ").append(column).append(" = ?");
            arguments.add(value);
        }
    }

    private static String escape(String value) {
        return value.replace("!", "!!").replace("%", "!%").replace("_", "!_");
    }

    private static Row row(ResultSet row, int index) throws SQLException {
        return new Row(
            row.getObject("audit_id", UUID.class),
            row.getTimestamp("occurred_at").toInstant(),
            response(
                "audit_id", row.getObject("audit_id").toString(),
                "occurred_at", row.getTimestamp("occurred_at").toInstant().toString(),
                "actor_type", row.getString("actor_type"),
                "actor_id", row.getString("actor_id"),
                "actor_ip", row.getString("actor_ip"),
                "action", row.getString("action"),
                "resource_type", row.getString("resource_type"),
                "resource_id", row.getString("resource_id"),
                "before_digest", row.getString("before_digest"),
                "after_digest", row.getString("after_digest"),
                "reason", row.getString("reason"),
                "request_id", row.getString("request_id"),
                "trace_id", row.getString("trace_id"),
                "result", row.getString("result"),
                "error_code", row.getString("error_code")
            )
        );
    }

    private static String encode(Row row) {
        String value = row.occurredAt() + "|" + row.auditId();
        return Base64.getUrlEncoder().withoutPadding().encodeToString(
            value.getBytes(StandardCharsets.UTF_8)
        );
    }

    private static Cursor decode(String value) {
        try {
            String decoded = new String(
                Base64.getUrlDecoder().decode(value),
                StandardCharsets.UTF_8
            );
            String[] parts = decoded.split("\\|", 2);
            if (parts.length != 2) {
                throw new IllegalArgumentException("字段数量不符");
            }
            return new Cursor(Instant.parse(parts[0]), UUID.fromString(parts[1]));
        } catch (RuntimeException invalid) {
            throw new ContractValues.ContractInputViolation(
                "cursor 不符合审计分页契约",
                invalid
            );
        }
    }

    private static Map<String, Object> response(Object... pairs) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index < pairs.length; index += 2) {
            result.put(String.valueOf(pairs[index]), pairs[index + 1]);
        }
        return result;
    }

    private record Cursor(Instant occurredAt, UUID auditId) {
    }

    private record Row(
        UUID auditId,
        Instant occurredAt,
        Map<String, Object> response
    ) {
    }
}
