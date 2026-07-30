package com.tooldefect.business.capture.application;

import java.time.Clock;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.shared.application.CanonicalJson;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.OutboxRepository;
import com.tooldefect.business.shared.application.Uuid7Generator;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.messaging.OutboxEvent;
import com.tooldefect.business.storage.application.StorageApplicationService;

@Service
@ConditionalOnProperty(name = "td.storage.enabled", havingValue = "true")
public class CaptureWorkflowService {
    private final CaptureRepository captures;
    private final StorageApplicationService storage;
    private final OutboxRepository outbox;
    private final IdempotencyService idempotency;
    private final Uuid7Generator identifiers;
    private final Clock clock;

    public CaptureWorkflowService(
            CaptureRepository captures,
            StorageApplicationService storage,
            OutboxRepository outbox,
            IdempotencyService idempotency,
            Uuid7Generator identifiers,
            Clock clock) {
        this.captures = Objects.requireNonNull(captures);
        this.storage = Objects.requireNonNull(storage);
        this.outbox = Objects.requireNonNull(outbox);
        this.idempotency = Objects.requireNonNull(idempotency);
        this.identifiers = Objects.requireNonNull(identifiers);
        this.clock = Objects.requireNonNull(clock);
    }

    @Transactional
    public IdempotencyService.Response create(
            CaptureRegistration registration,
            UUID actorStationId,
            String idempotencyKey,
            Object request) {
        requireSameStation(registration.stationId(), actorStationId);
        return idempotency.execute(
            "createCapture",
            actorStationId.toString(),
            idempotencyKey,
            request,
            () -> {
                captures.insertCapture(
                    registration,
                    CanonicalJson.sha256(request)
                );
                List<Map<String, Object>> tickets = new ArrayList<>();
                for (CaptureImageRegistration image : registration.images()) {
                    UUID imageId = identifiers.next();
                    var ticket = storage.issueRawUpload(
                        imageId,
                        registration.captureId(),
                        registration.stationId(),
                        actorStationId,
                        registration.capturedAt()
                            .atZone(java.time.ZoneOffset.UTC)
                            .toLocalDate(),
                        image.imageRole(),
                        image.sizeBytes(),
                        image.sha256(),
                        image.mediaType(),
                        image.extension()
                    );
                    captures.attachImageMetadata(imageId, image);
                    Map<String, Object> upload = new LinkedHashMap<>();
                    upload.put("method", ticket.method());
                    upload.put("url", ticket.url().toString());
                    upload.put("headers", ticket.headers());
                    upload.put(
                        "expires_at",
                        DateTimeFormatter.ISO_INSTANT.format(ticket.expiresAt())
                    );
                    tickets.add(Map.of(
                        "image_id", imageId.toString(),
                        "upload", Map.copyOf(upload)
                    ));
                }
                return new IdempotencyService.Response(
                    201,
                    Map.of(
                        "capture_id", registration.captureId().toString(),
                        "status", "UPLOADING",
                        "images", List.copyOf(tickets)
                    )
                );
            }
        );
    }

    @Transactional
    public IdempotencyService.Response completeImage(
            UUID captureId,
            UUID imageId,
            UUID actorStationId,
            long sizeBytes,
            String sha256,
            String uploadReceipt,
            String idempotencyKey,
            Object request) {
        return idempotency.execute(
            "completeCaptureImage:" + captureId + ":" + imageId,
            actorStationId.toString(),
            idempotencyKey,
            request,
            () -> {
                var object = storage.confirm(
                    imageId,
                    captureId,
                    actorStationId,
                    sizeBytes,
                    sha256,
                    uploadReceipt
                );
                if (captures.allImagesAvailable(captureId)) {
                    captures.markReady(captureId);
                }
                return new IdempotencyService.Response(
                    200,
                    Map.of(
                        "image_id", imageId.toString(),
                        "sha256", object.expectedSha256(),
                        "state", "AVAILABLE"
                    )
                );
            }
        );
    }

    @Transactional
    public IdempotencyService.Response submit(
            UUID captureId,
            UUID actorStationId,
            String idempotencyKey,
            Object request) {
        return idempotency.execute(
            "submitCapture:" + captureId,
            actorStationId.toString(),
            idempotencyKey,
            request,
            () -> submitNew(captureId, actorStationId)
        );
    }

    private IdempotencyService.Response submitNew(
            UUID captureId,
            UUID actorStationId) {
        var context = captures.lockReadySubmission(captureId, actorStationId);
        if (context.images().isEmpty()) {
            throw new DomainViolation("采集事件没有可用必需图片");
        }
        UUID taskId = identifiers.next();
        captures.insertDetectionTask(taskId, context);
        captures.markSubmitted(captureId);

        UUID eventId = identifiers.next();
        UUID messageId = identifiers.next();
        String traceparent = traceparent();
        Map<String, Object> task = inferenceTask(
            context,
            taskId,
            messageId,
            traceparent
        );
        Map<String, Object> event = new LinkedHashMap<>();
        event.put("event_id", eventId.toString());
        event.put(
            "event_type",
            "tool_defect.outbox.inference_requested.v1"
        );
        event.put("aggregate_type", "detection_task");
        event.put("aggregate_id", taskId.toString());
        event.put(
            "occurred_at",
            DateTimeFormatter.ISO_INSTANT.format(clock.instant())
        );
        event.put("message_id", messageId.toString());
        event.put("traceparent", traceparent);
        event.put("payload", task);
        outbox.append(OutboxEvent.pending(
            eventId,
            "detection_task",
            taskId,
            "tool_defect.outbox.inference_requested.v1",
            "production.gpu.multitask",
            CanonicalJson.encode(event),
            clock.instant()
        ));
        return new IdempotencyService.Response(
            202,
            Map.of(
                "capture_id", captureId.toString(),
                "status", "SUBMITTED",
                "detection_task_id", taskId.toString(),
                "pipeline_version", context.pipelineVersion(),
                "poll_after_ms", 500
            )
        );
    }

    @Transactional(readOnly = true)
    public Map<String, Object> get(UUID captureId, UUID actorStationId) {
        return captures.findStatus(captureId, actorStationId)
            .orElseThrow(() -> new DomainViolation("采集事件不存在或不在设备范围"))
            .toContract();
    }

    @Transactional(readOnly = true)
    public Map<String, Object> reconcile(
            List<UUID> captureIds,
            UUID actorStationId) {
        if (captureIds.isEmpty() || captureIds.size() > 100) {
            throw new DomainViolation("批量对账数量必须为 1 到 100");
        }
        List<Map<String, Object>> items = captureIds.stream()
            .distinct()
            .map(id -> captures.findStatus(id, actorStationId))
            .flatMap(java.util.Optional::stream)
            .map(CaptureStatusView::toContract)
            .toList();
        return Map.of("items", items);
    }

    @Transactional
    public IdempotencyService.Response heartbeat(
            UUID deviceId,
            UUID actorStationId,
            String agentVersion,
            java.time.Instant reportedAt,
            Map<String, Object> snapshot,
            String idempotencyKey,
            Object request) {
        return idempotency.execute(
            "reportDeviceHeartbeat:" + deviceId,
            actorStationId.toString(),
            idempotencyKey,
            request,
            () -> {
                captures.updateHeartbeat(
                    deviceId,
                    actorStationId,
                    agentVersion,
                    reportedAt,
                    snapshot
                );
                return new IdempotencyService.Response(
                    200,
                    Map.of(
                        "accepted", true,
                        "request_id", identifiers.next().toString()
                    )
                );
            }
        );
    }

    private Map<String, Object> inferenceTask(
            CaptureRepository.SubmissionContext context,
            UUID taskId,
            UUID messageId,
            String traceparent) {
        Map<String, Object> pipeline = Map.of(
            "pipeline_id", context.pipelineId().toString(),
            "version", context.pipelineVersion(),
            "config_sha256", context.configSha256(),
            "preprocessor_version", context.preprocessorVersion(),
            "algorithm_version", context.algorithmVersion(),
            "model_version", context.modelVersion()
        );
        List<Map<String, Object>> images = context.images().stream()
            .map(image -> Map.<String, Object>of(
                "image_id", image.imageId().toString(),
                "kind", image.kind(),
                "object", Map.of(
                    "bucket", image.bucket(),
                    "object_key", image.objectKey(),
                    "object_version", image.objectVersion(),
                    "sha256", image.sha256(),
                    "size_bytes", image.sizeBytes(),
                    "media_type", image.mediaType()
                ),
                "width", image.width(),
                "height", image.height(),
                "image_role", image.imageRole()
            ))
            .toList();
        return Map.of(
            "event_type", "tool_defect.inference.task.v1",
            "message_id", messageId.toString(),
            "occurred_at", DateTimeFormatter.ISO_INSTANT.format(clock.instant()),
            "traceparent", traceparent,
            "detection_task_id", taskId.toString(),
            "capture_id", context.captureId().toString(),
            "pipeline", pipeline,
            "images", images,
            "deadline_at",
            DateTimeFormatter.ISO_INSTANT.format(clock.instant().plusSeconds(30))
        );
    }

    private String traceparent() {
        String traceId = identifiers.next().toString().replace("-", "");
        String spanId = identifiers.next().toString().replace("-", "")
            .substring(0, 16);
        return "00-" + traceId + "-" + spanId + "-01";
    }

    private static void requireSameStation(UUID expected, UUID actual) {
        if (!expected.equals(actual)) {
            throw new DomainViolation("设备无权创建其他工位采集事件");
        }
    }
}
