package com.tooldefect.business.deployment.infrastructure;

import com.tooldefect.business.deployment.application.DeploymentQueryRepository;
import com.tooldefect.business.deployment.application.DeploymentRepository;
import com.tooldefect.business.deployment.domain.DeploymentApprovalRole;
import com.tooldefect.business.deployment.domain.DeploymentEnvironment;
import com.tooldefect.business.deployment.domain.DeploymentNotFound;
import com.tooldefect.business.deployment.domain.DeploymentStatus;
import com.tooldefect.business.deployment.domain.DeploymentStrategy;
import com.tooldefect.business.deployment.domain.ModelDeployment;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

@Repository
public class JdbcDeploymentRepository implements DeploymentRepository, DeploymentQueryRepository {

    private final JdbcTemplate jdbc;

    public JdbcDeploymentRepository(JdbcTemplate jdbc) {
        this.jdbc = Objects.requireNonNull(jdbc);
    }

    @Override
    public Optional<ModelDeployment> findDeployment(UUID deploymentId) {
        var rows = jdbc.query(
            "SELECT * FROM model_deployment WHERE model_deployment_id = ?::uuid",
            JdbcDeploymentRepository::mapDeployment, deploymentId
        );
        return rows.stream().findFirst();
    }

    @Override
    public void insertDeployment(ModelDeployment deployment) {
        jdbc.update(
            """
            INSERT INTO model_deployment
            (model_deployment_id, model_version_id, environment, deployment_strategy,
             station_scope, traffic_ratio, approved_by, rollback_target_id, status,
             requested_by, rollback_model_version_id, quality_approved_by,
             quality_approved_at, release_approved_by, release_approved_at,
             warmup_evidence_sha256, metrics_gate_sha256, rollback_evidence_sha256,
             created_at, updated_at, record_version)
            VALUES (?::uuid, ?::uuid, ?, ?, CAST(? AS jsonb), ?, ?::uuid, ?::uuid,
                    ?, ?::uuid, ?::uuid, ?::uuid, ?::timestamptz, ?::uuid,
                    ?::timestamptz, ?, ?, ?, ?, ?, ?)""",
            deployment.deploymentId(), deployment.modelVersionId(),
            deployment.environment().name(), deployment.strategy().name(),
            deployment.stationIdsJson(), deployment.trafficRatio(),
            deployment.approvedBy(), null, deployment.status().name(),
            deployment.requestedBy(), deployment.rollbackModelVersionId(),
            deployment.qualityApprovedBy(), deployment.qualityApprovedAt(),
            deployment.approvedBy(), deployment.approvedAt(),
            deployment.warmupEvidenceSha256(), deployment.metricsGateSha256(),
            deployment.rollbackEvidenceSha256(),
            deployment.createdAt(), deployment.createdAt(), deployment.recordVersion()
        );
    }

    @Override
    public void updateDeployment(ModelDeployment deployment) {
        int count = jdbc.update(
            """
            UPDATE model_deployment SET
            status = ?, approved_by = ?::uuid,
            quality_approved_by = ?::uuid, quality_approved_at = ?::timestamptz,
            release_approved_by = ?::uuid, release_approved_at = ?::timestamptz,
            warmup_evidence_sha256 = ?, metrics_gate_sha256 = ?,
            rollback_evidence_sha256 = ?,
            record_version = ?, updated_at = now()
            WHERE model_deployment_id = ?::uuid
              AND record_version = ?
              AND status IN ('REQUESTED', 'APPROVED', 'ACTIVE')""",
            deployment.status().name(),
            deployment.approvedBy(),
            deployment.qualityApprovedBy(), deployment.qualityApprovedAt(),
            deployment.approvedBy(), deployment.approvedAt(),
            deployment.warmupEvidenceSha256(), deployment.metricsGateSha256(),
            deployment.rollbackEvidenceSha256(),
            deployment.recordVersion(), deployment.deploymentId(),
            deployment.recordVersion() - 1
        );
        if (count != 1) {
            throw new DeploymentNotFound("模型部署更新冲突或不存在: " + deployment.deploymentId());
        }
    }

    @Override
    public void appendApproval(
            UUID approvalId,
            UUID deploymentId,
            DeploymentApprovalRole role,
            String decision,
            UUID actorId,
            String reason,
            Instant createdAt) {
        jdbc.update(
            """
            INSERT INTO model_deployment_approval
            (approval_id, model_deployment_id, role, decision, actor_id, reason, created_at)
            VALUES (?::uuid, ?::uuid, ?, ?, ?::uuid, ?, ?)""",
            approvalId, deploymentId, role.name(), decision, actorId, reason, createdAt
        );
    }

    @Override
    public Map<String, Object> listDeployments(
            String actorId, UUID modelVersionId, int pageSize, String cursor) {
        return listDeployments(
            actorId, modelVersionId, null, pageSize, cursor
        );
    }

    @Override
    public Map<String, Object> listDeployments(
            String actorId,
            UUID modelVersionId,
            String status,
            int pageSize,
            String cursor) {
        List<Object> args = new ArrayList<>();
        StringBuilder sql = new StringBuilder(
            "SELECT md.model_deployment_id AS deployment_id, md.model_version_id, " +
            "md.environment, md.deployment_strategy AS strategy, md.status, " +
            "md.release_approved_by AS approved_by, md.created_at " +
            "FROM model_deployment md WHERE 1=1 "
        );
        if (modelVersionId != null) {
            sql.append("AND md.model_version_id = ?::uuid ");
            args.add(modelVersionId);
        }
        if (status != null && !status.isBlank()) {
            sql.append("AND md.status = ? ");
            args.add(status);
        }
        if (cursor != null && !cursor.isBlank()) {
            sql.append("AND md.created_at < ?::timestamptz ");
            args.add(parseCursor(cursor));
        }
        sql.append("ORDER BY md.created_at DESC LIMIT ?");
        args.add(pageSize + 1);
        List<Map<String, Object>> rows = jdbc.queryForList(sql.toString(), args.toArray());
        boolean hasMore = rows.size() > pageSize;
        if (hasMore) {
            rows = rows.subList(0, pageSize);
        }
        List<Map<String, Object>> items = rows.stream()
            .map(JdbcDeploymentRepository::deploymentSummary)
            .toList();
        String nextCursor = null;
        if (hasMore && !rows.isEmpty()) {
            nextCursor = ((java.sql.Timestamp) rows.get(rows.size() - 1)
                .get("created_at")).toInstant().toString();
        }
        Map<String, Object> page = new LinkedHashMap<>();
        page.put("items", items);
        page.put("next_cursor", nextCursor);
        page.put("has_more", hasMore);
        return page;
    }

    @Override
    public Map<String, Object> detailDeployment(String actorId, UUID deploymentId) {
        return jdbc.queryForMap(
            "SELECT * FROM model_deployment WHERE model_deployment_id = ?::uuid",
            deploymentId
        );
    }

    @Override
    public Map<String, Object> listByStatus(
            String actorId, String status, int pageSize, String cursor) {
        return listDeployments(
            actorId, null, status, pageSize, cursor
        );
    }

    private static Map<String, Object> deploymentSummary(
            Map<String, Object> row) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("deployment_id", String.valueOf(row.get("deployment_id")));
        result.put(
            "model_version_id", String.valueOf(row.get("model_version_id"))
        );
        result.put("environment", String.valueOf(row.get("environment")));
        result.put("strategy", String.valueOf(row.get("strategy")));
        result.put("status", String.valueOf(row.get("status")));
        result.put(
            "created_at",
            ((java.sql.Timestamp) row.get("created_at")).toInstant().toString()
        );
        return result;
    }

    private static Instant parseCursor(String cursor) {
        try {
            return Instant.parse(cursor);
        } catch (java.time.DateTimeException invalid) {
            throw new com.tooldefect.business.shared.api.ContractValues
                .ContractInputViolation(
                    "cursor 不符合模型部署分页契约", invalid
                );
        }
    }

    private static ModelDeployment mapDeployment(ResultSet rs, int rowNum) throws SQLException {
        UUID releaseApprovedBy = uuid(rs, "release_approved_by");
        Instant releaseApprovedAt = timestamp(rs, "release_approved_at");
        return new ModelDeployment(
            uuid(rs, "model_deployment_id"),
            uuid(rs, "model_version_id"),
            DeploymentEnvironment.valueOf(rs.getString("environment")),
            DeploymentStrategy.valueOf(rs.getString("deployment_strategy")),
            rs.getString("station_scope"),
            rs.getDouble("traffic_ratio"),
            uuid(rs, "requested_by"),
            uuid(rs, "rollback_model_version_id"),
            uuid(rs, "quality_approved_by"),
            timestamp(rs, "quality_approved_at"),
            releaseApprovedBy,
            releaseApprovedAt,
            rs.getString("warmup_evidence_sha256"),
            rs.getString("metrics_gate_sha256"),
            rs.getString("rollback_evidence_sha256"),
            DeploymentStatus.valueOf(rs.getString("status")),
            rs.getTimestamp("created_at").toInstant(),
            rs.getLong("record_version")
        );
    }

    private static Instant timestamp(ResultSet rs, String column) throws SQLException {
        var value = rs.getTimestamp(column);
        return value == null ? null : value.toInstant();
    }

    private static UUID uuid(ResultSet rs, String column) throws SQLException {
        String value = rs.getString(column);
        return value != null ? UUID.fromString(value) : null;
    }
}
