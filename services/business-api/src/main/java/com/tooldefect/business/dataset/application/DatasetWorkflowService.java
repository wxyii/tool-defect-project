package com.tooldefect.business.dataset.application;

import com.tooldefect.business.dataset.domain.DatasetVersion;
import com.tooldefect.business.dataset.domain.DatasetVersionState;
import com.tooldefect.business.dataset.domain.DatasetNotFound;
import com.tooldefect.business.dataset.domain.CandidateManifest;
import com.tooldefect.business.shared.application.IdempotencyService;
import com.tooldefect.business.shared.application.Uuid7Generator;
import com.tooldefect.business.shared.domain.DomainViolation;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.Instant;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

@Service
public class DatasetWorkflowService {

    private final DatasetRepository datasets;
    private final IdempotencyService idempotency;
    private final Uuid7Generator identifiers;
    private final Clock clock;

    public DatasetWorkflowService(
            DatasetRepository datasets,
            IdempotencyService idempotency,
            Uuid7Generator identifiers,
            Clock clock) {
        this.datasets = Objects.requireNonNull(datasets);
        this.idempotency = Objects.requireNonNull(idempotency);
        this.identifiers = Objects.requireNonNull(identifiers);
        this.clock = Objects.requireNonNull(clock);
    }

    @Transactional
    public IdempotencyService.Response createVersion(
            String actorId, String idempotencyKey, Map<String, Object> request) {
        return idempotency.execute(
            "createDatasetVersion", actorId, idempotencyKey, request,
            () -> {
                var datasetId = requiredUuid(request, "dataset_id");
                var candidateManifestId = requiredUuid(request, "candidate_manifest_id");
                var purpose = requiredPurpose(request);
                var candidate = datasets.findCandidateManifest(candidateManifestId)
                    .orElseThrow(() -> new DomainViolation(
                        "候选清单未在业务库登记，数据集版本创建进入 HOLD"
                    ));
                if (!datasetId.equals(candidate.datasetId())) {
                    throw new DomainViolation("候选清单与数据集不匹配");
                }
                if (candidate.approvalState() != CandidateManifest.ApprovalState.APPROVED) {
                    throw new DomainViolation("候选清单尚未完成独立质量审批，不能创建数据集版本");
                }
                UUID requester = requiredActor(actorId);
                if (requester.equals(candidate.approvedBy())) {
                    throw new DomainViolation("候选清单审批人不能兼任数据集版本发起人");
                }

                var latest = datasets.findLatestVersion(datasetId);
                String nextVersion = latest.map(DatasetWorkflowService::nextVersion).orElse("1");
                UUID parentId = latest.map(DatasetVersion::datasetVersionId).orElse(null);

                var version = new DatasetVersion(
                    identifiers.next(),
                    datasetId,
                    nextVersion,
                    parentId,
                    candidate.candidateManifestId(),
                    purpose,
                    candidate.manifestObjectKey(),
                    candidate.manifestBucket(),
                    candidate.manifestSha256(),
                    candidate.sampleCount(),
                    "{}",
                    DatasetVersionState.BUILDING,
                    null,
                    Instant.now(clock),
                    null,
                    0
                );

                datasets.insertVersion(version);

                return new IdempotencyService.Response(202, Map.of(
                    "job_id", version.datasetVersionId().toString(),
                    "status", "QUEUED",
                    "poll_after_ms", 1000
                ));
            }
        );
    }

    @Transactional
    public IdempotencyService.Response approveVersion(
            String actorId, String idempotencyKey, UUID datasetVersionId, Map<String, Object> request) {
        return idempotency.execute(
            "approveDatasetVersion:" + datasetVersionId, actorId, idempotencyKey, request,
            () -> {
                var version = datasets.findVersion(datasetVersionId)
                    .orElseThrow(() -> new DatasetNotFound(datasetVersionId));

                if (version.state() == DatasetVersionState.FROZEN) {
                    return new IdempotencyService.Response(200, Map.of(
                        "dataset_version_id", version.datasetVersionId().toString(),
                        "state", version.state().name(),
                        "message", "数据集版本已冻结"
                    ));
                }

                var decision = (String) request.get("decision");
                if ("APPROVE".equals(decision)) {
                    var approved = version.withApproval(
                        UUID.fromString(actorId), Instant.now(clock));
                    datasets.updateVersion(approved);
                    return new IdempotencyService.Response(200, Map.of(
                        "dataset_version_id", approved.datasetVersionId().toString(),
                        "version", approved.version(),
                        "state", approved.state().name(),
                        "approved_at", approved.approvedAt().toString()
                    ));
                } else if ("REJECT".equals(decision)) {
                    var rejected = version.withState(DatasetVersionState.REJECTED);
                    datasets.updateVersion(rejected);
                    return new IdempotencyService.Response(200, Map.of(
                        "dataset_version_id", rejected.datasetVersionId().toString(),
                        "state", rejected.state().name()
                    ));
                }
                throw new DomainViolation("审批决定必须是 APPROVE 或 REJECT");
            }
        );
    }

    @Transactional(readOnly = true)
    public Map<String, Object> getVersion(UUID datasetVersionId) {
        var version = datasets.findVersion(datasetVersionId)
            .orElseThrow(() -> new DatasetNotFound(datasetVersionId));
        return Map.of(
            "id", version.datasetVersionId().toString(),
            "version", version.version(),
            "status", version.state().name(),
            "created_at", version.createdAt().toString()
        );
    }

    private static UUID requiredUuid(Map<String, Object> request, String field) {
        Object value = request.get(field);
        if (!(value instanceof String text) || text.isBlank()) {
            throw new DomainViolation(field + " 不能为空");
        }
        try {
            return UUID.fromString(text);
        } catch (IllegalArgumentException error) {
            throw new DomainViolation(field + " 不是合法 UUID");
        }
    }

    private static String requiredPurpose(Map<String, Object> request) {
        Object value = request.get("purpose");
        if (!(value instanceof String text) || text.isBlank() || text.length() > 256) {
            throw new DomainViolation("purpose 不能为空且不能超过 256 字符");
        }
        return text;
    }

    private static UUID requiredActor(String actorId) {
        try {
            return UUID.fromString(actorId);
        } catch (IllegalArgumentException error) {
            throw new DomainViolation("未认证用户不能创建数据集版本");
        }
    }

    private static String nextVersion(DatasetVersion latest) {
        try {
            return new java.math.BigInteger(latest.version())
                .add(java.math.BigInteger.ONE)
                .toString();
        } catch (NumberFormatException error) {
            throw new DomainViolation(
                "已有数据集版本不是可递增的数字版本，当前只能 HOLD"
            );
        }
    }
}
