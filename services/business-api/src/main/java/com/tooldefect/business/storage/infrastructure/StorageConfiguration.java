package com.tooldefect.business.storage.infrastructure;

import java.net.URI;
import java.security.SecureRandom;
import java.time.Clock;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.storage.application.ObjectKeyPolicy;
import com.tooldefect.business.storage.application.ObjectStoragePort;
import com.tooldefect.business.storage.application.StationScopeAuthorizer;
import com.tooldefect.business.storage.application.StorageApplicationService;
import com.tooldefect.business.storage.application.StoredObjectRepository;
import com.tooldefect.business.storage.application.UploadSessionRepository;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.http.urlconnection.UrlConnectionHttpClient;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.S3Configuration;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
public class StorageConfiguration {

    @Bean(destroyMethod = "close")
    S3Client s3Client(StorageProperties properties) {
        validate(properties);
        S3Configuration serviceConfiguration = S3Configuration.builder()
            .pathStyleAccessEnabled(properties.pathStyleAccess())
            .build();
        var builder = S3Client.builder()
            .credentialsProvider(credentials(properties))
            .region(Region.of(properties.region()))
            .serviceConfiguration(serviceConfiguration)
            .httpClientBuilder(UrlConnectionHttpClient.builder());
        if (properties.endpoint() != null) {
            builder.endpointOverride(properties.endpoint());
        }
        return builder.build();
    }

    @Bean(destroyMethod = "close")
    S3Presigner s3Presigner(StorageProperties properties) {
        validate(properties);
        S3Configuration serviceConfiguration = S3Configuration.builder()
            .pathStyleAccessEnabled(properties.pathStyleAccess())
            .build();
        var builder = S3Presigner.builder()
            .credentialsProvider(credentials(properties))
            .region(Region.of(properties.region()))
            .serviceConfiguration(serviceConfiguration);
        URI publicEndpoint = properties.publicEndpoint() == null
            ? properties.endpoint()
            : properties.publicEndpoint();
        if (publicEndpoint != null) {
            builder.endpointOverride(publicEndpoint);
        }
        return builder.build();
    }

    @Bean
    S3ClientFacade s3ClientFacade(
            S3Client client,
            S3Presigner presigner,
            StorageProperties properties) {
        return new AwsS3ClientFacade(
            client,
            presigner,
            properties.maximumObjectBytes(),
            properties.maximumPixels(),
            properties.maximumDecodedBytes()
        );
    }

    @Bean
    ObjectStoragePort objectStoragePort(
            S3ClientFacade client,
            Clock clock,
            StorageProperties properties) {
        return new S3CompatibleStorageAdapter(
            client,
            clock
        );
    }

    @Bean
    StorageApplicationService storageApplicationService(
            StoredObjectRepository objects,
            UploadSessionRepository sessions,
            ObjectStoragePort storage,
            StationScopeAuthorizer authorizer,
            Clock clock,
            SecureRandom secureRandom,
            StorageProperties properties) {
        return new StorageApplicationService(
            objects,
            sessions,
            storage,
            authorizer,
            new ObjectKeyPolicy(),
            clock,
            secureRandom,
            properties.rawBucket(),
            properties.uploadTtl(),
            properties.readTtl(),
            properties.maximumObjectBytes(),
            properties.maximumPixels(),
            properties.maximumDecodedBytes()
        );
    }

    private static StaticCredentialsProvider credentials(StorageProperties properties) {
        return StaticCredentialsProvider.create(AwsBasicCredentials.create(
            properties.accessKey(),
            properties.secretKey()
        ));
    }

    private static void validate(StorageProperties properties) {
        requireText(properties.region(), "S3 区域");
        requireText(properties.accessKey(), "S3 访问密钥");
        requireText(properties.secretKey(), "S3 机密密钥");
        requireText(properties.rawBucket(), "S3 原图桶");
        if (properties.endpoint() != null
                && properties.requireTls()
                && !"https".equalsIgnoreCase(properties.endpoint().getScheme())) {
            throw new DomainViolation("启用对象存储 TLS 时端点必须使用 HTTPS");
        }
        if (properties.publicEndpoint() != null
                && !"https".equalsIgnoreCase(
                    properties.publicEndpoint().getScheme())) {
            throw new DomainViolation("对象存储公开签名端点必须使用 HTTPS");
        }
    }

    private static void requireText(String value, String name) {
        if (value == null || value.isBlank()) {
            throw new DomainViolation(name + "未配置");
        }
    }
}
