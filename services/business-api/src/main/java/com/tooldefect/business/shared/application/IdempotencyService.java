package com.tooldefect.business.shared.application;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.function.Supplier;

import com.tooldefect.business.shared.domain.IdempotencyConflict;

public final class IdempotencyService {
    private final IdempotencyRepository repository;

    public IdempotencyService(IdempotencyRepository repository) {
        this.repository = Objects.requireNonNull(repository);
    }

    public Response execute(
            String operation,
            String actorId,
            String idempotencyKey,
            Object request,
            Supplier<Response> action) {
        requireText(operation, "operation");
        requireText(actorId, "actorId");
        if (idempotencyKey == null
                || idempotencyKey.length() < 8
                || idempotencyKey.length() > 256) {
            throw new IdempotencyConflict("Idempotency-Key 不合法");
        }
        String requestSha256 = CanonicalJson.sha256(request);
        repository.lock(operation, actorId, idempotencyKey);
        var existing = repository.find(operation, actorId, idempotencyKey);
        if (existing.isPresent()) {
            if (!existing.get().requestSha256().equals(requestSha256)) {
                throw new IdempotencyConflict(
                    "相同幂等键绑定了不同请求摘要"
                );
            }
            return new Response(
                existing.get().responseStatus(),
                existing.get().responseBody(),
                true
            );
        }
        Response response = Objects.requireNonNull(action.get());
        repository.insert(
            operation,
            actorId,
            idempotencyKey,
            requestSha256,
            response.status(),
            response.body()
        );
        return response;
    }

    private static void requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " 不能为空");
        }
    }

    public record Response(
        int status,
        Map<String, Object> body,
        boolean replay
    ) {
        public Response(int status, Map<String, Object> body) {
            this(status, body, false);
        }

        public Response {
            if (status < 200 || status > 599) {
                throw new IllegalArgumentException("HTTP 状态码不合法");
            }
            body = Collections.unmodifiableMap(
                new LinkedHashMap<>(Objects.requireNonNull(body))
            );
        }
    }
}
