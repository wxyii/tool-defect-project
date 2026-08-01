package com.tooldefect.business.audit.application;

import java.time.Clock;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.audit.domain.AuditRecord;
import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.application.Uuid7Generator;

@Service
public class AuditQueryService {
    private final AuditQueryRepository queries;
    private final AuditTrail audit;
    private final Uuid7Generator identifiers;
    private final Clock clock;

    public AuditQueryService(
            AuditQueryRepository queries,
            AuditTrail audit,
            Uuid7Generator identifiers,
            Clock clock) {
        this.queries = Objects.requireNonNull(queries);
        this.audit = Objects.requireNonNull(audit);
        this.identifiers = Objects.requireNonNull(identifiers);
        this.clock = Objects.requireNonNull(clock);
    }

    /** 查询成功后在同一事务追加一条查询审计；审计写入失败则整个请求失败。 */
    @Transactional
    public Map<String, Object> list(
            Instant startTime,
            Instant endTime,
            String cursor,
            int pageSize,
            String filterActorId,
            String action,
            String resourceType,
            String resourceId,
            String result,
            String queryingActorId,
            String actorIp,
            String requestId,
            String traceId) {
        Map<String, Object> response = queries.list(
            startTime,
            endTime,
            cursor,
            pageSize,
            filterActorId,
            action,
            resourceType,
            resourceId,
            result
        );
        Map<String, Object> criteria = new LinkedHashMap<>();
        criteria.put("start_time", startTime.toString());
        criteria.put("end_time", endTime.toString());
        criteria.put("cursor", cursor);
        criteria.put("page_size", pageSize);
        criteria.put("actor_id", filterActorId);
        criteria.put("action", action);
        criteria.put("resource_type", resourceType);
        criteria.put("resource_id", resourceId);
        criteria.put("result", result);
        audit.append(new AuditRecord(
            identifiers.next(),
            Instant.now(clock),
            "USER",
            queryingActorId,
            actorIp,
            "audit.records.query",
            "audit_log",
            startTime + "/" + endTime,
            null,
            CanonicalJson.sha256(criteria),
            "只读审计查询",
            requestId,
            traceId,
            "SUCCESS",
            null
        ));
        return response;
    }
}
