package com.tooldefect.business.storage.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.net.URI;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;

import org.junit.jupiter.api.Test;

import com.tooldefect.business.shared.domain.DomainViolation;

final class S3CompatibleStorageAdapterTest {
    private static final Clock CLOCK = Clock.fixed(
        Instant.parse("2026-08-03T00:00:00Z"),
        ZoneOffset.UTC
    );
    private static final String SHA256 = "a".repeat(64);

    @Test
    void localHttpPresignedUrlIsAllowedWhenTlsIsDisabled() {
        var adapter = new S3CompatibleStorageAdapter(
            facade(URI.create("http://127.0.0.1:9000/td-raw/object")),
            CLOCK,
            false
        );

        var authorization = adapter.authorizeUpload(
            "td-raw",
            "object.png",
            10,
            SHA256,
            "image/png",
            Map.of("x-amz-meta-test", "value"),
            Duration.ofMinutes(5)
        );

        assertThat(authorization.url()).hasScheme("http");
    }

    @Test
    void nonLoopbackHttpPresignedUrlIsRejectedEvenWhenTlsIsDisabled() {
        var adapter = new S3CompatibleStorageAdapter(
            facade(URI.create("http://object-storage:9000/td-raw/object")),
            CLOCK,
            false
        );

        assertThatThrownBy(() -> adapter.authorizeUpload(
            "td-raw",
            "object.png",
            10,
            SHA256,
            "image/png",
            Map.of(),
            Duration.ofMinutes(5)
        ))
            .isInstanceOf(DomainViolation.class)
            .hasMessage("签名地址必须使用 HTTPS");
    }

    @Test
    void httpPresignedUrlRemainsRejectedWhenTlsIsRequired() {
        var adapter = new S3CompatibleStorageAdapter(
            facade(URI.create("http://127.0.0.1:9000/td-raw/object")),
            CLOCK
        );

        assertThatThrownBy(() -> adapter.authorizeUpload(
            "td-raw",
            "object.png",
            10,
            SHA256,
            "image/png",
            Map.of(),
            Duration.ofMinutes(5)
        ))
            .isInstanceOf(DomainViolation.class)
            .hasMessage("签名地址必须使用 HTTPS");
    }

    private static S3ClientFacade facade(URI url) {
        return new S3ClientFacade() {
            @Override
            public PresignedRequest presignPut(
                    String bucket,
                    String objectKey,
                    long sizeBytes,
                    String sha256,
                    String mediaType,
                    Map<String, String> metadata,
                    Duration ttl) {
                return new PresignedRequest(url, Map.of());
            }

            @Override
            public PresignedRequest presignGet(
                    String bucket,
                    String objectKey,
                    Duration ttl) {
                return new PresignedRequest(url, Map.of());
            }

            @Override
            public HeadResult headAndInspect(String bucket, String objectKey) {
                throw new UnsupportedOperationException();
            }

            @Override
            public void delete(String bucket, String objectKey) {
                throw new UnsupportedOperationException();
            }
        };
    }
}
