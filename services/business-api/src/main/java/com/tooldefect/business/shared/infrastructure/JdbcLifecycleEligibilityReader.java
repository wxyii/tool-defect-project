package com.tooldefect.business.shared.infrastructure;

import com.tooldefect.business.shared.application.LifecycleEligibilityReader;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/** 只读跨生命周期资格查询；不替代各领域仓储的写入职责。 */
@Repository
public class JdbcLifecycleEligibilityReader implements LifecycleEligibilityReader {

    private final JdbcTemplate jdbc;

    public JdbcLifecycleEligibilityReader(JdbcTemplate jdbc) {
        this.jdbc = Objects.requireNonNull(jdbc);
    }

    @Override
    public Optional<TrainingEvidence> findTraining(UUID trainingRunId) {
        return jdbc.query(
            """
            SELECT dataset_version_id, status, registry_run_uri, started_at, finished_at
            FROM training_run
            WHERE training_run_id = ?::uuid
            """,
            (row, rowNumber) -> new TrainingEvidence(
                UUID.fromString(row.getString("dataset_version_id")),
                row.getString("status"),
                row.getString("registry_run_uri"),
                instant(row.getTimestamp("started_at")),
                instant(row.getTimestamp("finished_at"))
            ),
            trainingRunId
        ).stream().findFirst();
    }

    @Override
    public Optional<DatasetEvidence> findDataset(UUID datasetVersionId) {
        return jdbc.query(
            """
            SELECT status, manifest_bucket, manifest_object_key, manifest_sha256
            FROM dataset_version
            WHERE dataset_version_id = ?::uuid
            """,
            (row, rowNumber) -> new DatasetEvidence(
                row.getString("status"),
                row.getString("manifest_bucket"),
                row.getString("manifest_object_key"),
                row.getString("manifest_sha256")
            ),
            datasetVersionId
        ).stream().findFirst();
    }

    @Override
    public Optional<ModelEvidence> findModel(UUID modelVersionId) {
        return jdbc.query(
            """
            SELECT approval_state, training_run_id, dataset_version_id,
                   registry_name, registry_version, registered_by,
                   sbom_sha256, signature_key_id,
                   evaluation_report_sha256, threshold_gate_sha256
            FROM model_version
            WHERE model_version_id = ?::uuid
            """,
            (row, rowNumber) -> new ModelEvidence(
                row.getString("approval_state"),
                uuid(row.getString("training_run_id")),
                uuid(row.getString("dataset_version_id")),
                row.getString("registry_name"),
                row.getString("registry_version"),
                uuid(row.getString("registered_by")),
                row.getString("sbom_sha256"),
                row.getString("signature_key_id"),
                row.getString("evaluation_report_sha256"),
                row.getString("threshold_gate_sha256")
            ),
            modelVersionId
        ).stream().findFirst();
    }

    private static Instant instant(Timestamp value) {
        return value == null ? null : value.toInstant();
    }

    private static UUID uuid(String value) {
        return value == null ? null : UUID.fromString(value);
    }
}
