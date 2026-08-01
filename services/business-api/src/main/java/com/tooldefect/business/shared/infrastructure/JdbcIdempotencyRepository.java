package com.tooldefect.business.shared.infrastructure;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.PreparedStatementCallback;
import org.springframework.stereotype.Repository;

import tools.jackson.databind.ObjectMapper;

import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.application.IdempotencyRepository;
import com.tooldefect.business.shared.domain.DomainViolation;

@Repository
public class JdbcIdempotencyRepository implements IdempotencyRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;

    public JdbcIdempotencyRepository(JdbcTemplate jdbc, ObjectMapper json) {
        this.jdbc = java.util.Objects.requireNonNull(jdbc);
        this.json = java.util.Objects.requireNonNull(json);
    }

    @Override
    public void lock(String operation, String actorId, String idempotencyKey) {
        jdbc.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (PreparedStatementCallback<Void>) statement -> {
                statement.setString(
                    1,
                    operation + "\u001f" + actorId + "\u001f" + idempotencyKey
                );
                statement.execute();
                return null;
            }
        );
    }

    @Override
    public Optional<StoredResponse> find(
            String operation,
            String actorId,
            String idempotencyKey) {
        return jdbc.query(
            """
            SELECT request_sha256,
                   response_status,
                   response_body::text AS response_body
            FROM idempotency_record
            WHERE operation = ?
              AND actor_id = ?
              AND idempotency_key = ?
            """,
            (row, rowNumber) -> new StoredResponse(
                row.getString("request_sha256").trim(),
                row.getInt("response_status"),
                parseObject(row.getString("response_body"))
            ),
            operation,
            actorId,
            idempotencyKey
        ).stream().findFirst();
    }

    @Override
    public void insert(
            String operation,
            String actorId,
            String idempotencyKey,
            String requestSha256,
            int responseStatus,
            Map<String, Object> responseBody) {
        int inserted = jdbc.update(
            """
            INSERT INTO idempotency_record(
                operation,
                actor_id,
                idempotency_key,
                request_sha256,
                response_status,
                response_body
            )
            VALUES (?, ?, ?, ?, ?, CAST(? AS jsonb))
            """,
            operation,
            actorId,
            idempotencyKey,
            requestSha256,
            responseStatus,
            CanonicalJson.encode(responseBody)
        );
        if (inserted != 1) {
            throw new DomainViolation("幂等响应保存失败");
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseObject(String value) {
        try {
            Object decoded = json.readValue(value, Map.class);
            if (!(decoded instanceof Map<?, ?> map)) {
                throw new DomainViolation("幂等响应不是 JSON 对象");
            }
            Map<String, Object> result = new LinkedHashMap<>();
            for (var entry : map.entrySet()) {
                if (!(entry.getKey() instanceof String key)) {
                    throw new DomainViolation("幂等响应包含非字符串键");
                }
                result.put(key, entry.getValue());
            }
            return result;
        } catch (DomainViolation error) {
            throw error;
        } catch (Exception error) {
            throw new DomainViolation("幂等响应无法解码", error);
        }
    }
}
