package com.tooldefect.business;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.awt.Color;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Map;
import java.util.UUID;

import javax.imageio.ImageIO;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.MinIOContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

import com.tooldefect.business.storage.application.StorageApplicationService;
import com.tooldefect.business.storage.domain.StorageIntegrityViolation;

import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.CreateBucketRequest;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 以真实 PostgreSQL 和 MinIO 验证续签端点、JWT 工位范围、签名上传、元数据
 * 绑定、流式哈希与最终 AVAILABLE 状态。
 */
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
@Import(S3StorageIT.JwtTestConfiguration.class)
@Testcontainers(disabledWithoutDocker = false)
class S3StorageIT {
    private static final UUID STATION_ID = UUID.fromString(
        "019f0000-0000-7000-8000-000000000301"
    );
    private static final UUID OTHER_STATION_ID = UUID.fromString(
        "019f0000-0000-7000-8000-000000000302"
    );

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

    private static final HttpClient HTTP = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build();

    @LocalServerPort
    int applicationPort;

    @Autowired
    JdbcTemplate jdbc;

    @Autowired
    S3Client s3;

    @Autowired
    StorageApplicationService storage;

    @Autowired
    ObjectMapper json;

    @DynamicPropertySource
    static void infrastructureProperties(DynamicPropertyRegistry registry) {
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

    @Test
    void renewEndpointUploadsBoundObjectAndRejectsScopeOrDigestSubstitution()
            throws Exception {
        ensureBucket();
        byte[] png = png();
        String sha256 = sha256(png);
        Fixture fixture = seedStagingImage(png.length, sha256);
        String path = "/api/v1/edge/captures/"
            + fixture.captureId()
            + "/images/"
            + fixture.imageId()
            + "/upload-ticket";

        HttpResponse<String> noScope = renew(
            path,
            "no-scope",
            "renew-key-no-scope",
            png.length,
            sha256,
            false
        );
        assertThat(noScope.statusCode()).isEqualTo(403);
        assertStandardError(
            noScope,
            "TD-SECURITY-AUTHORIZATION-001",
            false
        );

        HttpResponse<String> wrongStation = renew(
            path,
            "other-station",
            "renew-key-other-station",
            png.length,
            sha256,
            false
        );
        assertThat(wrongStation.statusCode()).isEqualTo(403);
        assertStandardError(
            wrongStation,
            "TD-SECURITY-AUTHORIZATION-001",
            false
        );

        HttpResponse<String> wrongDigest = renew(
            path,
            "station",
            "renew-key-wrong-digest",
            png.length,
            "f".repeat(64),
            false
        );
        assertThat(wrongDigest.statusCode()).isEqualTo(409);
        assertStandardError(wrongDigest, "TD-API-CONFLICT-001", false);

        HttpResponse<String> unknownField = renew(
            path,
            "station",
            "renew-key-unknown-field",
            png.length,
            sha256,
            true
        );
        assertThat(unknownField.statusCode()).isEqualTo(422);
        assertStandardError(unknownField, "TD-API-VALIDATION-001", false);

        HttpResponse<String> renewal = renew(
            path,
            "station",
            "renew-key-success",
            png.length,
            sha256,
            false
        );
        assertThat(renewal.statusCode()).isEqualTo(200);
        JsonNode response = json.readTree(renewal.body());
        assertThat(response.path("image_id").asString())
            .isEqualTo(fixture.imageId().toString());
        JsonNode upload = response.path("upload");
        assertThat(upload.path("method").asString()).isEqualTo("PUT");
        assertThat(upload.path("url").asString()).startsWith("https://");
        assertThat(Instant.parse(upload.path("expires_at").asString()))
            .isAfter(Instant.now());
        assertThat(upload.path("headers").size()).isLessThanOrEqualTo(8);

        String receipt = upload.path("headers")
            .path(StorageApplicationService.UPLOAD_RECEIPT_HEADER)
            .asString(null);
        assertThat(receipt).isNotBlank();

        // 第一次确认时对象尚未到达，后端返回可重试完整性失败，但必须保留
        // 同一 image_id 的一次续签恢复机会。
        String failedReceipt = receipt;
        assertThatThrownBy(() -> storage.confirm(
            fixture.imageId(),
            fixture.captureId(),
            STATION_ID,
            png.length,
            sha256,
            failedReceipt
        )).isInstanceOf(StorageIntegrityViolation.class);
        assertThat(jdbc.queryForObject(
            "SELECT state FROM image_object WHERE image_id = ?",
            String.class,
            fixture.imageId()
        )).isEqualTo("STAGING");

        HttpResponse<String> recoveryRenewal = renew(
            path,
            "station",
            "renew-key-integrity-recovery",
            png.length,
            sha256,
            false
        );
        assertThat(recoveryRenewal.statusCode()).isEqualTo(200);
        response = json.readTree(recoveryRenewal.body());
        upload = response.path("upload");
        receipt = upload.path("headers")
            .path(StorageApplicationService.UPLOAD_RECEIPT_HEADER)
            .asString(null);
        assertThat(receipt).isNotBlank().isNotEqualTo(failedReceipt);
        HttpRequest.Builder put = HttpRequest.newBuilder()
            // MinIO 测试容器没有 TLS；仅把传输 scheme 改回 HTTP，主机、路径、
            // 查询和签名保持不变。API 返回值仍严格验证为 HTTPS。
            .uri(URI.create(
                upload.path("url").asString().replaceFirst("^https://", "http://")
            ))
            .timeout(Duration.ofSeconds(20))
            .PUT(HttpRequest.BodyPublishers.ofByteArray(png));
        upload.path("headers").properties().forEach(header -> {
            if (!header.getKey().equals(
                    StorageApplicationService.UPLOAD_RECEIPT_HEADER)) {
                put.header(header.getKey(), header.getValue().asString());
            }
        });
        HttpResponse<String> uploaded = HTTP.send(
            put.build(),
            HttpResponse.BodyHandlers.ofString()
        );
        assertThat(uploaded.statusCode()).isIn(200, 204);

        var confirmed = storage.confirm(
            fixture.imageId(),
            fixture.captureId(),
            STATION_ID,
            png.length,
            sha256,
            receipt
        );
        assertThat(confirmed.state().name()).isEqualTo("AVAILABLE");
        assertThat(confirmed.width()).isEqualTo(3);
        assertThat(confirmed.height()).isEqualTo(2);
        assertThat(jdbc.queryForObject(
            "SELECT state FROM image_object WHERE image_id = ?",
            String.class,
            fixture.imageId()
        )).isEqualTo("AVAILABLE");
        assertThat(jdbc.queryForObject(
            """
            SELECT COUNT(*) FROM upload_session
            WHERE image_id = ? AND status = 'CONFIRMED'
            """,
            Integer.class,
            fixture.imageId()
        )).isEqualTo(1);

        var repeated = storage.confirm(
            fixture.imageId(),
            fixture.captureId(),
            STATION_ID,
            png.length,
            sha256,
            receipt
        );
        assertThat(repeated.state().name()).isEqualTo("AVAILABLE");
        assertThat(repeated.recordVersion()).isEqualTo(1);
    }

    private HttpResponse<String> renew(
            String path,
            String token,
            String idempotencyKey,
            long size,
            String sha256,
            boolean unknownField) throws Exception {
        Map<String, Object> body = unknownField
            ? Map.of(
                "size_bytes", size,
                "sha256", sha256,
                "unexpected", true
            )
            : Map.of("size_bytes", size, "sha256", sha256);
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create("http://127.0.0.1:" + applicationPort + path))
            .timeout(Duration.ofSeconds(10))
            .header("Authorization", "Bearer " + token)
            .header("Idempotency-Key", idempotencyKey)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(
                json.writeValueAsString(body)
            ))
            .build();
        return HTTP.send(request, HttpResponse.BodyHandlers.ofString());
    }

    private void assertStandardError(
            HttpResponse<String> response,
            String code,
            boolean retryable) throws Exception {
        JsonNode error = json.readTree(response.body());
        assertThat(error.path("code").asString()).isEqualTo(code);
        assertThat(error.path("message").asString()).isNotBlank();
        assertThat(error.path("request_id").asString())
            .matches("^[0-9a-f-]{36}$");
        assertThat(error.path("trace_id").asString())
            .matches("^[0-9a-f]{32}$");
        assertThat(error.path("retryable").asBoolean()).isEqualTo(retryable);
        assertThat(error.path("details").isArray()).isTrue();
    }

    private void ensureBucket() {
        boolean exists = s3.listBuckets().buckets().stream()
            .anyMatch(bucket -> "td-raw".equals(bucket.name()));
        if (!exists) {
            s3.createBucket(CreateBucketRequest.builder().bucket("td-raw").build());
        }
    }

    private Fixture seedStagingImage(long sizeBytes, String sha256) {
        UUID organizationId = UUID.randomUUID();
        UUID lineId = UUID.randomUUID();
        UUID recipeId = UUID.randomUUID();
        UUID captureId = UUID.randomUUID();
        UUID imageId = UUID.randomUUID();
        jdbc.update(
            """
            INSERT INTO organization(
                organization_id, organization_code, organization_name, status
            ) VALUES (?, ?, '存储测试组织', 'ACTIVE')
            """,
            organizationId,
            "storage-org-" + organizationId
        );
        jdbc.update(
            """
            INSERT INTO production_line(
                line_id, organization_id, line_code, line_name, status
            ) VALUES (?, ?, ?, '存储测试产线', 'ACTIVE')
            """,
            lineId,
            organizationId,
            "storage-line-" + lineId
        );
        jdbc.update(
            """
            INSERT INTO capture_recipe(
                recipe_id, recipe_name, version, config,
                config_sha256, status
            ) VALUES (?, ?, '1', '{}'::jsonb, ?, 'APPROVED')
            """,
            recipeId,
            "storage-recipe-" + recipeId,
            "a".repeat(64)
        );
        jdbc.update(
            """
            INSERT INTO station(
                station_id, line_id, station_code, station_name,
                active_recipe_id, status
            ) VALUES (?, ?, ?, '存储测试工位', ?, 'ACTIVE')
            """,
            STATION_ID,
            lineId,
            "storage-station-" + UUID.randomUUID(),
            recipeId
        );
        jdbc.update(
            """
            INSERT INTO capture_event(
                capture_id, station_id, trigger_id, client_sequence,
                source_type, captured_at, recipe_id, status,
                quality_status, request_digest
            ) VALUES (?, ?, ?, 1, 'ONLINE', now(), ?, 'UPLOADING', 'OK', ?)
            """,
            captureId,
            STATION_ID,
            "storage-trigger-" + captureId,
            recipeId,
            "b".repeat(64)
        );
        jdbc.update(
            """
            INSERT INTO image_object(
                image_id, capture_id, kind, bucket, object_key,
                sha256, size_bytes, media_type, state
            ) VALUES (?, ?, 'RAW', 'td-raw', ?, ?, ?, 'image/png', 'STAGING')
            """,
            imageId,
            captureId,
            "raw/2026/07/29/" + STATION_ID + "/" + captureId + "/raw.png",
            sha256,
            sizeBytes
        );
        return new Fixture(captureId, imageId);
    }

    private static byte[] png() throws Exception {
        BufferedImage image = new BufferedImage(3, 2, BufferedImage.TYPE_INT_RGB);
        image.setRGB(0, 0, Color.RED.getRGB());
        image.setRGB(1, 0, Color.GREEN.getRGB());
        image.setRGB(2, 0, Color.BLUE.getRGB());
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        assertThat(ImageIO.write(image, "png", output)).isTrue();
        return output.toByteArray();
    }

    private static String sha256(byte[] value) throws Exception {
        return HexFormat.of().formatHex(
            MessageDigest.getInstance("SHA-256").digest(value)
        );
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class JwtTestConfiguration {
        @Bean
        JwtDecoder testJwtDecoder() {
            return token -> {
                UUID station = "other-station".equals(token)
                    ? OTHER_STATION_ID
                    : STATION_ID;
                String scope = "no-scope".equals(token) ? "" : "capture:write";
                Instant now = Instant.now();
                return Jwt.withTokenValue(token)
                    .header("alg", "none")
                    .subject("edge-test")
                    .issuedAt(now.minusSeconds(1))
                    .expiresAt(now.plusSeconds(300))
                    .claim("station_id", station.toString())
                    .claim("scope", scope)
                    .build();
            };
        }
    }

    private record Fixture(UUID captureId, UUID imageId) {
    }
}
