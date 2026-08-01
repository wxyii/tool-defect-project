package com.tooldefect.business.model.infrastructure;

import com.tooldefect.business.model.application.ModelQueryRepository;
import com.tooldefect.business.model.application.ModelRepository;
import com.tooldefect.business.model.domain.ModelApprovalState;
import com.tooldefect.business.model.domain.ModelNotFound;
import com.tooldefect.business.model.domain.ModelVersion;
import com.tooldefect.business.shared.domain.DomainViolation;

import org.springframework.dao.DuplicateKeyException;
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
public class JdbcModelRepository implements ModelRepository, ModelQueryRepository {

    private final JdbcTemplate jdbc;

    public JdbcModelRepository(JdbcTemplate jdbc) {
        this.jdbc = Objects.requireNonNull(jdbc);
    }

    @Override
    public void insertModel(
            UUID modelId,
            String modelName,
            String taskType,
            Instant createdAt) {
        try {
            jdbc.update(
                """
                INSERT INTO model
                (model_id, model_name, task_type, created_at)
                VALUES (?::uuid, ?, ?, ?)
                """,
                modelId, modelName, taskType,
                java.sql.Timestamp.from(createdAt)
            );
        } catch (DuplicateKeyException duplicate) {
            throw new DomainViolation("模型名称已存在", duplicate);
        }
    }

    @Override
    public Optional<ModelVersion> findVersion(UUID modelVersionId) {
        var rows = jdbc.query(
            "SELECT * FROM model_version WHERE model_version_id = ?::uuid",
            JdbcModelRepository::mapVersion, modelVersionId
        );
        return rows.stream().findFirst();
    }

    @Override
    public void insertVersion(ModelVersion version) {
        jdbc.update(
            """
            INSERT INTO model_version
            (model_version_id, model_id, version, training_run_id,
             dataset_version_id, registry_name, registry_version,
             artifact_bucket, artifact_object_key, artifact_sha256,
             sbom_sha256, signature_key_id, input_spec, output_spec,
             evaluation_summary, evaluation_report_sha256, threshold_gate_sha256,
             approval_state, registered_by, validated_by, validated_at,
             approved_by, approved_at, created_at)
            VALUES (?::uuid, ?::uuid, CAST(? AS varchar), ?::uuid, ?::uuid, ?, ?,
                    ?, ?, ?, ?, CAST(? AS jsonb), CAST(? AS jsonb), CAST(? AS jsonb),
                    ?, ?, ?, ?, ?::uuid, ?::uuid, ?::timestamptz,
                    ?::uuid, ?::timestamptz, ?)""",
            version.modelVersionId(), version.modelId(), version.version(),
            version.trainingRunId(), version.datasetVersionId(),
            version.registryName(), version.registryVersion(),
            version.artifactBucket(), version.artifactObjectKey(),
            version.artifactSha256(),
            version.sbomSha256(), version.signatureKeyId(),
            version.inputSpecJson(), version.outputSpecJson(),
            version.evaluationSummaryJson(),
            version.evaluationReportSha256(), version.thresholdGateSha256(),
            version.approvalState().name(), version.registeredBy(),
            version.validatedBy(), version.validatedAt(),
            version.approvedBy(), version.approvedAt(),
            version.createdAt()
        );
    }

    @Override
    public void updateVersion(ModelVersion version) {
        String sql = """
            UPDATE model_version SET
            approval_state = ?,
            evaluation_summary = CAST(? AS jsonb),
            validated_by = ?::uuid,
            validated_at = ?::timestamptz,
            approved_by = ?::uuid,
            approved_at = ?::timestamptz
            WHERE model_version_id = ?::uuid
              AND approval_state IN (""" + previousStatesForUpdate(version.approvalState()) + ")";
        int count = jdbc.update(
            sql,
            version.approvalState().name(),
            version.evaluationSummaryJson(),
            version.validatedBy(), version.validatedAt(),
            version.approvedBy(), version.approvedAt(),
            version.modelVersionId()
        );
        if (count != 1) {
            throw new ModelNotFound("模型版本更新冲突或不存在: " + version.modelVersionId());
        }
    }

    @Override
    public void appendApproval(
            UUID approvalId,
            UUID modelVersionId,
            String stage,
            String decision,
            UUID actorId,
            String reason,
            Instant createdAt) {
        jdbc.update(
            """
            INSERT INTO model_version_approval
            (approval_id, model_version_id, stage, decision, actor_id, reason, created_at)
            VALUES (?::uuid, ?::uuid, ?, ?, ?::uuid, ?, ?)""",
            approvalId, modelVersionId, stage, decision, actorId, reason, createdAt
        );
    }

    @Override
    public Optional<ModelVersion> findLatestVersion(UUID modelId) {
        var rows = jdbc.query(
            "SELECT * FROM model_version WHERE model_id = ?::uuid ORDER BY version::int DESC LIMIT 1",
            JdbcModelRepository::mapVersion, modelId
        );
        return rows.stream().findFirst();
    }

    @Override
    public Optional<ModelVersion> findVersionByRegistryName(String name, String version) {
        var rows = jdbc.query(
            "SELECT * FROM model_version WHERE registry_name = ? AND registry_version = ?",
            JdbcModelRepository::mapVersion, name, version
        );
        return rows.stream().findFirst();
    }

    @Override
    public Map<String, Object> listModels(
            String actorId, int pageSize, String cursor) {
        List<Object> args = new ArrayList<>();
        StringBuilder sql = new StringBuilder("""
            SELECT m.model_id, m.model_name, m.task_type, m.created_at,
                   (SELECT COUNT(*) FROM model_version counted
                    WHERE counted.model_id = m.model_id) AS version_count,
                   (SELECT latest.version::int FROM model_version latest
                    WHERE latest.model_id = m.model_id
                    ORDER BY latest.version::int DESC LIMIT 1) AS latest_version,
                   (SELECT latest.approval_state FROM model_version latest
                    WHERE latest.model_id = m.model_id
                    ORDER BY latest.version::int DESC LIMIT 1) AS latest_approval_state
            FROM model m
            WHERE 1=1
            """);
        if (cursor != null && !cursor.isBlank()) {
            sql.append("AND m.created_at < ?::timestamptz ");
            args.add(Instant.parse(cursor));
        }
        sql.append("ORDER BY m.created_at DESC LIMIT ?");
        args.add(pageSize + 1);
        List<Map<String, Object>> rows = jdbc.queryForList(
            sql.toString(), args.toArray()
        );
        boolean hasMore = rows.size() > pageSize;
        if (hasMore) rows = rows.subList(0, pageSize);
        List<Map<String, Object>> items = rows.stream()
            .map(JdbcModelRepository::modelSummary)
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
    public Map<String, Object> listVersions(
            String actorId,
            UUID modelId,
            int pageSize,
            String cursor) {
        return listVersions(actorId, modelId, null, pageSize, cursor);
    }

    @Override
    public Map<String, Object> listVersions(
            String actorId,
            UUID modelId,
            String approvalState,
            int pageSize,
            String cursor) {
        List<Object> args = new ArrayList<>();
        StringBuilder sql = new StringBuilder(
            "SELECT mv.model_version_id, mv.model_id, mv.version::int AS version, mv.registry_name, " +
            "mv.registry_version, mv.approval_state, mv.created_at " +
            "FROM model_version mv WHERE 1=1 "
        );
        if (modelId != null) {
            sql.append("AND mv.model_id = ?::uuid ");
            args.add(modelId);
        }
        if (approvalState != null && !approvalState.isBlank()) {
            sql.append("AND mv.approval_state = ? ");
            args.add(approvalState);
        }
        if (cursor != null) {
            sql.append("AND mv.created_at < ?::timestamptz ");
            args.add(Instant.parse(cursor));
        }
        sql.append("ORDER BY mv.version DESC LIMIT ?");
        args.add(pageSize + 1);
        List<Map<String, Object>> rows = jdbc.queryForList(sql.toString(), args.toArray());
        boolean hasMore = rows.size() > pageSize;
        if (hasMore) {
            rows = rows.subList(0, pageSize);
        }
        String nextCursor = null;
        if (hasMore && !rows.isEmpty()) {
            nextCursor = String.valueOf(rows.get(rows.size() - 1).get("created_at"));
        }
        Map<String, Object> page = new LinkedHashMap<>();
        page.put("items", rows);
        page.put("next_cursor", nextCursor);
        page.put("has_more", hasMore);
        return page;
    }

    @Override
    public Map<String, Object> detailVersion(String actorId, UUID modelVersionId) {
        return jdbc.queryForMap(
            "SELECT * FROM model_version WHERE model_version_id = ?::uuid",
            modelVersionId
        );
    }

    @Override
    public Map<String, Object> listByState(String actorId, String approvalState, int pageSize, String cursor) {
        return listVersions(
            actorId, null, approvalState, pageSize, cursor
        );
    }

    private static Map<String, Object> modelSummary(
            Map<String, Object> row) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("model_id", String.valueOf(row.get("model_id")));
        result.put("model_name", String.valueOf(row.get("model_name")));
        result.put("task_type", String.valueOf(row.get("task_type")));
        result.put(
            "version_count",
            ((Number) row.get("version_count")).intValue()
        );
        result.put(
            "latest_version",
            row.get("latest_version") == null
                ? null : ((Number) row.get("latest_version")).intValue()
        );
        result.put(
            "latest_approval_state",
            row.get("latest_approval_state") == null
                ? null : String.valueOf(row.get("latest_approval_state"))
        );
        result.put(
            "created_at",
            ((java.sql.Timestamp) row.get("created_at")).toInstant().toString()
        );
        return result;
    }

    private static String previousStateForUpdate(ModelApprovalState newState) {
        if (newState == ModelApprovalState.VALIDATED) {
            return ModelApprovalState.CANDIDATE.name();
        }
        if (newState == ModelApprovalState.APPROVED) {
            return ModelApprovalState.VALIDATED.name();
        }
        return null;
    }

    private static String previousStatesForUpdate(ModelApprovalState newState) {
        if (newState == ModelApprovalState.REJECTED) {
            return "'CANDIDATE', 'VALIDATED'";
        }
        return "'" + previousStateForUpdate(newState) + "'";
    }

    private static ModelVersion mapVersion(ResultSet rs, int rowNum) throws SQLException {
        return new ModelVersion(
            uuid(rs, "model_version_id"),
            uuid(rs, "model_id"),
            rs.getInt("version"),
            uuid(rs, "training_run_id"),
            uuid(rs, "dataset_version_id"),
            rs.getString("registry_name"),
            rs.getString("registry_version"),
            rs.getString("artifact_bucket"),
            rs.getString("artifact_object_key"),
            rs.getString("artifact_sha256"),
            rs.getString("sbom_sha256"),
            rs.getString("signature_key_id"),
            rs.getString("input_spec"),
            rs.getString("output_spec"),
            rs.getString("evaluation_summary"),
            rs.getString("evaluation_report_sha256"),
            rs.getString("threshold_gate_sha256"),
            ModelApprovalState.valueOf(rs.getString("approval_state")),
            uuid(rs, "registered_by"),
            uuid(rs, "validated_by"),
            timestamp(rs, "validated_at"),
            uuid(rs, "approved_by"),
            timestamp(rs, "approved_at"),
            rs.getTimestamp("created_at").toInstant()
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
