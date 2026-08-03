package com.tooldefect.business.storage.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;

import org.junit.jupiter.api.Test;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.http.urlconnection.UrlConnectionHttpClient;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;

final class AwsS3ClientFacadeTest {
    @Test
    void browserUploadTicketDoesNotSignContentLength() {
        var credentials = StaticCredentialsProvider.create(
            AwsBasicCredentials.create("test-access", "test-secret")
        );
        try (var client = S3Client.builder()
                .httpClient(UrlConnectionHttpClient.builder().build())
                .endpointOverride(URI.create("http://127.0.0.1:9000"))
                .region(Region.US_EAST_1)
                .credentialsProvider(credentials)
                .forcePathStyle(true)
                .build();
             var presigner = S3Presigner.builder()
                .endpointOverride(URI.create("http://127.0.0.1:9000"))
                .region(Region.US_EAST_1)
                .credentialsProvider(credentials)
                .build()) {
            var ticket = new AwsS3ClientFacade(
                client,
                presigner,
                50_000_000L,
                10_000_000L,
                200_000_000L
            ).presignPut(
                "td-raw",
                "manual-originals/test/signature.png",
                10L,
                "a".repeat(64),
                "image/png",
                Map.of("batch-id", "batch", "batch-item-id", "item"),
                Duration.ofMinutes(5)
            );

            String signedHeaders = URLDecoder.decode(
                queryParameter(ticket.url(), "X-Amz-SignedHeaders"),
                StandardCharsets.UTF_8
            );
            assertThat(ticket.headers()).doesNotContainKey("content-length");
            assertThat(signedHeaders.split(";"))
                .doesNotContain("content-length");
        }
    }

    private static String queryParameter(URI uri, String name) {
        for (String parameter : uri.getRawQuery().split("&")) {
            String[] parts = parameter.split("=", 2);
            if (parts.length == 2 && name.equals(parts[0])) return parts[1];
        }
        throw new AssertionError("预签名地址缺少参数：" + name);
    }
}
