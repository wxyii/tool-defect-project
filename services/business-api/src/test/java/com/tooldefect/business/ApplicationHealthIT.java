package com.tooldefect.business;

import static org.assertj.core.api.Assertions.assertThat;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalManagementPort;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.ApplicationContext;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

/** 启动完整应用并验证管理端口隔离、健康探针最小披露和默认拒绝。 */
@SpringBootTest(
    webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = {
        "server.address=127.0.0.1",
        "management.server.address=127.0.0.1",
        "management.server.port=0",
        "management.endpoint.health.show-details=never",
        "td.storage.enabled=false",
        "td.messaging.enabled=false"
    }
)
@Testcontainers(disabledWithoutDocker = false)
class ApplicationHealthIT {
    @Container
    static final PostgreSQLContainer POSTGRES = new PostgreSQLContainer(
        DockerImageName.parse("postgres:18.4-alpine")
    )
        .withDatabaseName("tool_defect_health")
        .withUsername("tool_defect_test")
        .withPassword("tool-defect-test-only");

    private static final HttpClient HTTP = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .build();

    @LocalServerPort
    int applicationPort;

    @LocalManagementPort
    int managementPort;

    @Autowired
    ApplicationContext context;

    @DynamicPropertySource
    static void databaseProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
    }

    @Test
    void applicationStartsWithRestrictedHealthOnSeparateLoopbackPort()
            throws Exception {
        assertThat(managementPort).isNotEqualTo(applicationPort);
        assertThat(context.getBeansOfType(UserDetailsService.class)).isEmpty();

        HttpResponse<String> health = get(managementPort, "/actuator/health");
        assertThat(health.statusCode()).isEqualTo(200);
        assertThat(health.body()).contains("\"status\":\"UP\"");
        assertThat(health.body())
            .doesNotContain("components")
            .doesNotContain("jdbc:")
            .doesNotContain(POSTGRES.getUsername());

        HttpResponse<String> applicationHealth = get(
            applicationPort,
            "/actuator/health"
        );
        assertThat(applicationHealth.statusCode()).isIn(401, 404);

        HttpResponse<String> internal = get(
            applicationPort,
            "/internal/v1/build"
        );
        assertThat(internal.statusCode()).isIn(401, 403);

        HttpResponse<String> metrics = get(
            managementPort,
            "/actuator/prometheus"
        );
        assertThat(metrics.statusCode()).isIn(401, 403);
    }

    private static HttpResponse<String> get(int port, String path)
            throws Exception {
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create("http://127.0.0.1:" + port + path))
            .timeout(Duration.ofSeconds(10))
            .GET()
            .build();
        return HTTP.send(request, HttpResponse.BodyHandlers.ofString());
    }
}
