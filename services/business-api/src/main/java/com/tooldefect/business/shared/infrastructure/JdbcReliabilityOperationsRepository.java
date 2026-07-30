package com.tooldefect.business.shared.infrastructure;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.application.ReliabilityOperationsRepository;
import com.tooldefect.business.shared.domain.DomainViolation;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

@Repository
public class JdbcReliabilityOperationsRepository
        implements ReliabilityOperationsRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;

    public JdbcReliabilityOperationsRepository(
            JdbcTemplate jdbc,
            ObjectMapper json) {
        this.jdbc = java.util.Objects.requireNonNull(jdbc);
        this.json = java.util.Objects.requireNonNull(json);
    }

    @Override
    public List<IssueCandidate> discoverDatabaseIssues(
            Instant stagingBefore,
            int limit) {
        List<IssueCandidate> dead = jdbc.query("""
            SELECT event_id::text AS resource_id,
                   aggregate_id AS capture_id,
                   jsonb_build_object(
                       'event_type', event_type,
                       'attempt_count', attempt_count,
                       'last_error', last_error
                   )::text AS observed_state
            FROM outbox_event
            WHERE status = 'DEAD'
            ORDER BY created_at, event_id
            LIMIT ?
            """,
            (row, index) -> new IssueCandidate(
                IssueType.OUTBOX_DEAD,
                Severity.HIGH,
                "outbox_event",
                row.getString("resource_id"),
                row.getObject("capture_id", UUID.class),
                decodeMap(row.getString("observed_state"))
            ),
            limit
        );
        if (dead.size() >= limit) {
            return dead;
        }
        List<IssueCandidate> staging = jdbc.query("""
            SELECT image_id::text AS resource_id,
                   capture_id,
                   jsonb_build_object(
                       'bucket', bucket,
                       'object_key', object_key,
                       'state', state,
                       'updated_at', updated_at
                   )::text AS observed_state
            FROM image_object
            WHERE state = 'STAGING'
              AND updated_at <= ?
            ORDER BY updated_at, image_id
            LIMIT ?
            """,
            (row, index) -> new IssueCandidate(
                IssueType.STAGING_OBJECT_ORPHANED,
                Severity.HIGH,
                "image_object",
                row.getString("resource_id"),
                row.getObject("capture_id", UUID.class),
                decodeMap(row.getString("observed_state"))
            ),
            Timestamp.from(stagingBefore),
            limit - dead.size()
        );
        var all = new java.util.ArrayList<IssueCandidate>(dead);
        all.addAll(staging);
        return List.copyOf(all);
    }

    @Override
    public boolean appendIssue(Issue issue) {
        return jdbc.update("""
            INSERT INTO reliability_issue(
                issue_id,
                issue_fingerprint,
                issue_type,
                severity,
                resource_type,
                resource_id,
                capture_id,
                observed_state,
                detected_at,
                request_id,
                trace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CAST(? AS jsonb), ?, ?, ?)
            ON CONFLICT (issue_fingerprint) DO NOTHING
            """,
            issue.issueId(),
            issue.fingerprint(),
            issue.issueType().name(),
            issue.severity().name(),
            issue.resourceType(),
            issue.resourceId(),
            issue.captureId(),
            CanonicalJson.encode(issue.observedState()),
            Timestamp.from(issue.detectedAt()),
            issue.requestId(),
            issue.traceId()
        ) == 1;
    }

    @Override
    public Optional<Issue> findIssue(UUID issueId) {
        return jdbc.query("""
            SELECT issue_id,
                   issue_fingerprint,
                   issue_type,
                   severity,
                   resource_type,
                   resource_id,
                   capture_id,
                   observed_state::text,
                   detected_at,
                   request_id,
                   trace_id
            FROM reliability_issue
            WHERE issue_id = ?
            """,
            (row, index) -> new Issue(
                row.getObject("issue_id", UUID.class),
                row.getString("issue_fingerprint").trim(),
                IssueType.valueOf(row.getString("issue_type")),
                Severity.valueOf(row.getString("severity")),
                row.getString("resource_type"),
                row.getString("resource_id"),
                row.getObject("capture_id", UUID.class),
                decodeMap(row.getString("observed_state")),
                row.getTimestamp("detected_at").toInstant(),
                row.getString("request_id"),
                row.getString("trace_id").trim()
            ),
            issueId
        ).stream().findFirst();
    }

    @Override
    @Transactional
    public void applyAction(Issue issue, Action action) {
        int inserted = jdbc.update("""
            INSERT INTO maintenance_action(
                action_id,
                issue_id,
                action_type,
                replacement_resource_id,
                actor_id,
                actor_permissions,
                reason,
                request_id,
                trace_id,
                occurred_at
            ) VALUES (?, ?, ?, ?, ?, CAST(? AS jsonb), ?, ?, ?, ?)
            """,
            action.actionId(),
            action.issueId(),
            action.actionType().name(),
            action.replacementResourceId(),
            action.actorId(),
            CanonicalJson.encode(action.actorPermissions().stream().sorted().toList()),
            action.reason(),
            action.requestId(),
            action.traceId(),
            Timestamp.from(action.occurredAt())
        );
        if (inserted != 1) {
            throw new DomainViolation("可靠性人工处置记录写入失败");
        }
        if (action.actionType() == ActionType.RETRY_ORIGINAL) {
            if (issue.issueType() != IssueType.OUTBOX_DEAD
                    || !"outbox_event".equals(issue.resourceType())) {
                throw new DomainViolation("只有发件箱终止事件可以恢复原投递");
            }
            UUID eventId;
            try {
                eventId = UUID.fromString(issue.resourceId());
            } catch (IllegalArgumentException invalid) {
                throw new DomainViolation("发件箱问题资源标识不是 UUID", invalid);
            }
            int changed = jdbc.update("""
                UPDATE outbox_event
                SET status = 'FAILED',
                    next_attempt_at = ?,
                    claim_owner = NULL,
                    lease_until = NULL
                WHERE event_id = ?
                  AND status = 'DEAD'
                """,
                Timestamp.from(action.occurredAt()),
                eventId
            );
            if (changed != 1) {
                throw new DomainViolation("发件箱终止事件状态已变化，拒绝覆盖");
            }
        }
        Map<String, Object> after = new LinkedHashMap<>();
        after.put("issue_id", issue.issueId().toString());
        after.put("action_id", action.actionId().toString());
        after.put("action_type", action.actionType().name());
        after.put("replacement_resource_id", action.replacementResourceId());
        jdbc.update("""
            INSERT INTO audit_log(
                audit_id,
                occurred_at,
                actor_type,
                actor_id,
                action,
                resource_type,
                resource_id,
                after_digest,
                reason,
                request_id,
                trace_id,
                result
            ) VALUES (?, ?, 'HUMAN', ?, ?, 'reliability_issue', ?, ?, ?, ?, ?, 'SUCCESS')
            """,
            action.auditId(),
            Timestamp.from(action.occurredAt()),
            action.actorId(),
            "reliability." + action.actionType().name().toLowerCase(
                java.util.Locale.ROOT
            ),
            issue.issueId(),
            CanonicalJson.sha256(after),
            action.reason(),
            action.requestId(),
            action.traceId()
        );
    }

    private Map<String, Object> decodeMap(String value) {
        try {
            return java.util.Collections.unmodifiableMap(
                new LinkedHashMap<>(json.readValue(
                    value,
                    new TypeReference<Map<String, Object>>() {}
                ))
            );
        } catch (tools.jackson.core.JacksonException error) {
            throw new DomainViolation("可靠性问题状态不是合法 JSON", error);
        }
    }
}
