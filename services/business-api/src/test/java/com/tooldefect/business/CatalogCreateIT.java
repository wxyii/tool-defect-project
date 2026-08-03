package com.tooldefect.business;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.UUID;
import java.util.Map;

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

import com.tooldefect.business.model.application.ModelWorkflowService;

/** 在隔离数据库中验证保留的模型目录资源可以被真实创建。 */
@SpringBootTest(
    webEnvironment = SpringBootTest.WebEnvironment.NONE,
    properties = {
        "td.storage.enabled=false",
        "td.messaging.enabled=false",
        "td.operations.enabled=false"
    }
)
@Testcontainers(disabledWithoutDocker = false)
class CatalogCreateIT {
    @Container
    static final PostgreSQLContainer POSTGRES = new PostgreSQLContainer(
        DockerImageName.parse("postgres:18.4-alpine")
    )
        .withDatabaseName("tool_defect_catalog")
        .withUsername("tool_defect_test")
        .withPassword("tool-defect-test-only");

    @Autowired
    ModelWorkflowService models;

    @Autowired
    JdbcTemplate jdbc;

    @DynamicPropertySource
    static void databaseProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
    }

    @Test
    void createsModelCatalogEntry() {
        String actorId = UUID.randomUUID().toString();

        var model = models.createModel(
            actorId,
            UUID.randomUUID().toString(),
            Map.of(
                "model_name", "回归验证模型",
                "task_type", "classification-segmentation"
            )
        );

        assertThat(model.status()).isEqualTo(201);
        assertThat(jdbc.queryForObject(
            "SELECT COUNT(*) FROM model", Integer.class
        )).isEqualTo(1);
    }
}
