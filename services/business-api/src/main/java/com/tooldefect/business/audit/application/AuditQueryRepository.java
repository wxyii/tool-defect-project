package com.tooldefect.business.audit.application;

import java.time.Instant;
import java.util.Map;

public interface AuditQueryRepository {
    Map<String, Object> list(
        Instant startTime,
        Instant endTime,
        String cursor,
        int pageSize,
        String actorId,
        String action,
        String resourceType,
        String resourceId,
        String result
    );
}
