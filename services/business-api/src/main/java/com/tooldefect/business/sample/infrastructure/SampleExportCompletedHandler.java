package com.tooldefect.business.sample.infrastructure;

import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import com.tooldefect.business.sample.application.SampleLibraryRepository;
import com.tooldefect.business.sample.application.SampleViolation;
import com.tooldefect.business.shared.application.NonRetryableMessageException;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** 严格消费 worker 完成事件，并把终态投影写入业务数据库。 */
@Component
@ConditionalOnProperty(
    name = {"td.messaging.consumer.enabled", "td.sample-export.enabled", "td.storage.enabled"},
    havingValue = "true"
)
public final class SampleExportCompletedHandler {
    private static final Set<String> EVENT_FIELDS = Set.of(
        "message_id", "occurred_at", "idempotency_key", "traceparent",
        "sample_export_job_id", "package", "manifest", "exported_count",
        "failed_candidate_ids"
    );
    private static final Set<String> OBJECT_FIELDS = Set.of(
        "bucket", "object_key", "object_version", "sha256", "size_bytes", "media_type"
    );
    private static final String TRACEPARENT_PATTERN =
        "^00-[a-f0-9]{32}-[a-f0-9]{16}-[a-f0-9]{2}$";

    private final SampleLibraryRepository repository;
    private final ObjectMapper json;

    public SampleExportCompletedHandler(
            SampleLibraryRepository repository, ObjectMapper json) {
        this.repository = java.util.Objects.requireNonNull(repository);
        this.json = java.util.Objects.requireNonNull(json);
    }

    public void handle(String payloadJson) {
        CompletedEvent event = parse(payloadJson);
        try {
            repository.applyExportCompleted(
                event.jobId(), event.packageReference(), event.manifestReference(),
                event.exportedCount(), event.failedCandidateIds());
        } catch (SampleViolation violation) {
            throw new NonRetryableMessageException(
                "样本导出完成事件无法安全落库：" + violation.getMessage(), violation);
        }
    }

    private CompletedEvent parse(String payloadJson) {
        try {
            JsonNode root = json.readTree(payloadJson);
            exact(root, EVENT_FIELDS, EVENT_FIELDS, "样本导出完成事件");
            UUID.fromString(requiredText(root, "message_id"));
            Instant occurredAt = utcInstant(root, "occurred_at");
            String idempotencyKey = requiredText(root, "idempotency_key");
            if (idempotencyKey.length() < 8 || idempotencyKey.length() > 128) {
                invalid("幂等键长度非法");
            }
            String traceparent = requiredText(root, "traceparent");
            if (!traceparent.matches(TRACEPARENT_PATTERN)) {
                invalid("traceparent 不符合 v2 契约");
            }
            UUID jobId = UUID.fromString(requiredText(root, "sample_export_job_id"));
            SampleLibraryRepository.ObjectReference packageReference = objectReference(
                root.path("package"), "package", "application/zip");
            SampleLibraryRepository.ObjectReference manifestReference = objectReference(
                root.path("manifest"), "manifest", "application/json");
            if (!packageReference.objectKey().startsWith("sample-exports/")
                    || !manifestReference.objectKey().startsWith("sample-exports/")) {
                invalid("完成事件对象必须使用 sample-exports/ 前缀");
            }
            JsonNode exported = root.path("exported_count");
            if (!exported.isIntegralNumber() || exported.longValue() < 0
                    || exported.longValue() > Integer.MAX_VALUE) {
                invalid("exported_count 不合法");
            }
            List<UUID> failed = failedCandidateIds(root.path("failed_candidate_ids"));
            return new CompletedEvent(
                jobId, packageReference, manifestReference, exported.intValue(), failed,
                occurredAt);
        } catch (NonRetryableMessageException error) {
            throw error;
        } catch (RuntimeException error) {
            throw new NonRetryableMessageException(
                "样本导出完成事件不符合冻结 v2 契约", error);
        }
    }

    private static List<UUID> failedCandidateIds(JsonNode node) {
        if (!node.isArray() || node.size() > 10_000) {
            invalid("failed_candidate_ids 数组不合法");
        }
        Set<UUID> seen = new HashSet<>();
        java.util.ArrayList<UUID> values = new java.util.ArrayList<>();
        for (JsonNode value : node) {
            if (!value.isString()) {
                invalid("失败候选标识必须是字符串");
            }
            UUID candidate;
            try {
                candidate = UUID.fromString(value.stringValue());
            } catch (IllegalArgumentException invalidUuid) {
                invalid("失败候选标识不是 UUID");
                return List.of();
            }
            if (!seen.add(candidate)) {
                invalid("失败候选标识不能重复");
            }
            values.add(candidate);
        }
        return values.stream().sorted().toList();
    }

    private static SampleLibraryRepository.ObjectReference objectReference(
            JsonNode node, String name, String mediaType) {
        exact(node, Set.of("bucket", "object_key", "sha256", "size_bytes", "media_type"),
            OBJECT_FIELDS, name);
        String bucket = requiredText(node, "bucket");
        if (!bucket.matches("^[a-z0-9][a-z0-9.-]{1,126}$")) {
            invalid(name + " 桶名不合法");
        }
        String key = requiredText(node, "object_key");
        String sha256 = requiredText(node, "sha256");
        if (!sha256.matches("[0-9a-f]{64}")) {
            invalid(name + " SHA-256 不合法");
        }
        JsonNode size = node.path("size_bytes");
        if (!size.isIntegralNumber() || size.longValue() <= 0) {
            invalid(name + " 大小不合法");
        }
        if (!mediaType.equals(requiredText(node, "media_type"))) {
            invalid(name + " 媒体类型不合法");
        }
        String objectVersion = optionalText(node, "object_version");
        if (objectVersion != null && objectVersion.length() > 256) {
            invalid(name + " 对象版本过长");
        }
        return new SampleLibraryRepository.ObjectReference(
            bucket, key, objectVersion, sha256, size.longValue(), mediaType);
    }

    private static void exact(
            JsonNode node, Set<String> required, Set<String> allowed, String name) {
        if (!node.isObject()) {
            invalid(name + "必须是对象");
        }
        Set<String> actual = new HashSet<>();
        node.properties().forEach(entry -> actual.add(entry.getKey()));
        if (!actual.containsAll(required) || !allowed.containsAll(actual)) {
            invalid(name + "字段不符合冻结契约");
        }
    }

    private static String requiredText(JsonNode node, String field) {
        JsonNode value = node.path(field);
        if (!value.isString() || value.stringValue().isBlank()) {
            invalid(field + " 必须是非空字符串");
        }
        return value.stringValue();
    }

    private static String optionalText(JsonNode node, String field) {
        JsonNode value = node.path(field);
        return value.isMissingNode() || value.isNull() ? null : requiredText(node, field);
    }

    private static Instant utcInstant(JsonNode node, String field) {
        String value = requiredText(node, field);
        if (!value.endsWith("Z")) {
            invalid(field + " 必须是 UTC 时间");
        }
        return Instant.parse(value);
    }

    private static void invalid(String message) {
        throw new NonRetryableMessageException(message);
    }

    private record CompletedEvent(
            UUID jobId,
            SampleLibraryRepository.ObjectReference packageReference,
            SampleLibraryRepository.ObjectReference manifestReference,
            int exportedCount,
            List<UUID> failedCandidateIds,
            Instant occurredAt) {
    }
}
