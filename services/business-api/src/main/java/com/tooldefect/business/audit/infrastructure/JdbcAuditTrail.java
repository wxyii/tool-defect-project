package com.tooldefect.business.audit.infrastructure;

import java.sql.Timestamp;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import com.tooldefect.business.audit.application.AuditTrail;
import com.tooldefect.business.audit.domain.AuditRecord;
import com.tooldefect.business.shared.domain.DomainViolation;

@Repository
public class JdbcAuditTrail implements AuditTrail {
    private final JdbcTemplate jdbc;

    public JdbcAuditTrail(JdbcTemplate jdbc) {
        this.jdbc = java.util.Objects.requireNonNull(jdbc);
    }

    @Override
    public void append(AuditRecord record) {
        int inserted = jdbc.update(
            """
            INSERT INTO audit_log(
                audit_id,
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
            ) VALUES (?, ?, ?, ?, ?::inet, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            record.auditId(),
            Timestamp.from(record.occurredAt()),
            record.actorType(),
            record.actorId(),
            record.actorIp(),
            record.action(),
            record.resourceType(),
            record.resourceId(),
            record.beforeDigest(),
            record.afterDigest(),
            record.reason(),
            record.requestId(),
            record.traceId(),
            record.result(),
            record.errorCode()
        );
        if (inserted != 1) {
            throw new DomainViolation("审计记录写入失败");
        }
    }
}
