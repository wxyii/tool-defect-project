package com.tooldefect.business;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

import com.tooldefect.business.dataset.application.DatasetQueryService;
import com.tooldefect.business.dataset.application.DatasetWorkflowService;

/** 在隔离数据库中验证候选清单、版本构建和冻结审批的完整状态链。 */
@SpringBootTest(
    webEnvironment = SpringBootTest.WebEnvironment.NONE,
    properties = {
        "td.storage.enabled=false",
        "td.messaging.enabled=false",
        "td.operations.enabled=false"
    }
)
@Testcontainers(disabledWithoutDocker = false)
class DatasetBuildFlowIT {
    @Container
    static final PostgreSQLContainer POSTGRES = new PostgreSQLContainer(
        DockerImageName.parse("postgres:18.4-alpine")
    )
        .withDatabaseName("tool_defect_dataset_flow")
        .withUsername("tool_defect_test")
        .withPassword("tool-defect-test-only");

    @Autowired
    DatasetWorkflowService workflow;

    @Autowired
    DatasetQueryService queries;

    @Autowired
    JdbcTemplate jdbc;

    @DynamicPropertySource
    static void databaseProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
    }

    @Test
    @SuppressWarnings("unchecked")
    void buildsAndFreezesVersionFromIndependentlyApprovedManifest() {
        UUID requesterId = UUID.randomUUID();
        UUID approverId = UUID.randomUUID();
        UUID candidateManifestId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO sys_user(user_id, external_subject, display_name, status)
            VALUES (?::uuid, ?, '数据集审批人', 'ACTIVE')
            """,
            approverId,
            "dataset-approver-" + approverId
        );

        var datasetResponse = workflow.createDataset(
            requesterId.toString(),
            UUID.randomUUID().toString(),
            Map.of(
                "dataset_name", "完整构建流程数据集",
                "purpose", "验证候选清单到冻结版本"
            )
        );
        UUID datasetId = UUID.fromString(
            String.valueOf(datasetResponse.body().get("dataset_id"))
        );
        jdbc.update(
            """
            INSERT INTO dataset_candidate_manifest(
                candidate_manifest_id, dataset_id, manifest_bucket,
                manifest_object_key, manifest_sha256, sample_count,
                approval_state
            ) VALUES (?::uuid, ?::uuid, 'td-datasets', ?, ?, 172, 'REGISTERED')
            """,
            candidateManifestId,
            datasetId,
            "candidate/flow-" + candidateManifestId + "/manifest.csv",
            "a".repeat(64)
        );

        Map<String, Object> registeredPage = queries.listCandidateManifests(
            requesterId.toString(), datasetId, null, 50, null
        );
        assertThat((List<Map<String, Object>>) registeredPage.get("items"))
            .singleElement()
            .satisfies(item -> assertThat(item)
                .containsEntry("approval_state", "REGISTERED"));

        var manifestApproval = workflow.approveCandidateManifest(
            approverId.toString(),
            UUID.randomUUID().toString(),
            candidateManifestId,
            Map.of("decision", "APPROVE")
        );
        assertThat(manifestApproval.body())
            .containsEntry("approval_state", "APPROVED");

        var accepted = workflow.createVersion(
            requesterId.toString(),
            UUID.randomUUID().toString(),
            Map.of(
                "dataset_id", datasetId.toString(),
                "candidate_manifest_id", candidateManifestId.toString(),
                "purpose", "受控增量训练"
            )
        );
        UUID datasetVersionId = UUID.fromString(
            String.valueOf(accepted.body().get("job_id"))
        );
        jdbc.update(
            """
            UPDATE dataset_version
            SET status = 'VALIDATING', record_version = record_version + 1
            WHERE dataset_version_id = ?::uuid
            """,
            datasetVersionId
        );

        var versionApproval = workflow.approveVersion(
            approverId.toString(),
            UUID.randomUUID().toString(),
            datasetVersionId,
            Map.of("decision", "APPROVE")
        );

        assertThat(versionApproval.body())
            .containsEntry("dataset_version_id", datasetVersionId.toString())
            .containsEntry("state", "FROZEN")
            .containsEntry("message", "数据集版本已冻结");
        assertThat(jdbc.queryForObject(
            "SELECT status FROM dataset_version WHERE dataset_version_id = ?::uuid",
            String.class,
            datasetVersionId
        )).isEqualTo("FROZEN");
    }
}
