package com.tooldefect.business;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.MinIOContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

import com.tooldefect.business.storage.application.ObjectStoragePort;
import com.tooldefect.business.storage.domain.StorageIntegrityViolation;

import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.CreateBucketRequest;

/** 以真实 PostgreSQL 和 MinIO 验证第二版对象存储缺失对象时安全失败。 */
@SpringBootTest(
    webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = {
        "server.address=127.0.0.1",
        "management.server.address=127.0.0.1",
        "management.server.port=0",
        "td.storage.enabled=true",
        "td.storage.require-tls=false",
        "td.storage.raw-bucket=td-raw",
        "td.storage.maximum-object-bytes=1048576",
        "td.storage.maximum-pixels=10000",
        "td.storage.maximum-decoded-bytes=40000",
        "td.messaging.enabled=false"
    }
)
@Testcontainers(disabledWithoutDocker = false)
class S3StorageIT {
    @Container
    static final PostgreSQLContainer POSTGRES = new PostgreSQLContainer(
        DockerImageName.parse("postgres:18.4-alpine")
    )
        .withDatabaseName("tool_defect_storage")
        .withUsername("tool_defect_test")
        .withPassword("tool-defect-test-only");

    @Container
    static final MinIOContainer MINIO = new MinIOContainer(
        DockerImageName.parse(
            "minio/minio:RELEASE.2024-01-16T16-07-38Z"
        )
    )
        .withUserName("tooldefecttest")
        .withPassword("tool-defect-minio-test-only")
        .withEnv(
            "MINIO_KMS_SECRET_KEY",
            "td-test-key:MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
        );

    @Autowired
    S3Client s3;

    @Autowired
    ObjectStoragePort objectStorage;

    @Test
    void missingObjectHeadFailsSafe() {
        ensureBucket();
        String key = "manual-originals/test/orphan-missing.png";
        objectStorage.delete("td-raw", key);

        assertThatThrownBy(() -> objectStorage.head("td-raw", key))
            .isInstanceOf(StorageIntegrityViolation.class);
    }

    @DynamicPropertySource
    static void infrastructureProperties(
            org.springframework.test.context.DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("td.storage.endpoint", MINIO::getS3URL);
        registry.add(
            "td.storage.public-endpoint",
            () -> MINIO.getS3URL().replaceFirst("^http://", "https://")
        );
        registry.add("td.storage.access-key", MINIO::getUserName);
        registry.add("td.storage.secret-key", MINIO::getPassword);
    }

    private void ensureBucket() {
        boolean exists = s3.listBuckets().buckets().stream()
            .anyMatch(bucket -> "td-raw".equals(bucket.name()));
        if (!exists) {
            s3.createBucket(CreateBucketRequest.builder().bucket("td-raw").build());
        }
    }
}
