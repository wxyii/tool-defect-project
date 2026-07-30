package com.tooldefect.business.shared.application;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

public interface IdempotencyRepository {
    void lock(String operation, String actorId, String idempotencyKey);

    Optional<StoredResponse> find(
        String operation,
        String actorId,
        String idempotencyKey
    );

    void insert(
        String operation,
        String actorId,
        String idempotencyKey,
        String requestSha256,
        int responseStatus,
        Map<String, Object> responseBody
    );

    record StoredResponse(
        String requestSha256,
        int responseStatus,
        Map<String, Object> responseBody
    ) {
        public StoredResponse {
            responseBody = Collections.unmodifiableMap(
                new LinkedHashMap<>(responseBody)
            );
        }
    }
}
