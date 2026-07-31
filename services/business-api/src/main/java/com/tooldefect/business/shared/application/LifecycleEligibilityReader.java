package com.tooldefect.business.shared.application;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

/** 跨生命周期只读资格查询，避免训练与模型应用层互相依赖。 */
public interface LifecycleEligibilityReader {

    Optional<TrainingEvidence> findTraining(UUID trainingRunId);

    Optional<DatasetEvidence> findDataset(UUID datasetVersionId);

    Optional<ModelEvidence> findModel(UUID modelVersionId);

    record TrainingEvidence(
            UUID datasetVersionId,
            String status,
            String registryRunUri,
            Instant startedAt,
            Instant finishedAt) {

        public boolean hasSuccessfulEvidence() {
            return "SUCCEEDED".equals(status)
                    && registryRunUri != null
                    && !registryRunUri.isBlank()
                    && startedAt != null
                    && finishedAt != null
                    && !finishedAt.isBefore(startedAt);
        }
    }

    record DatasetEvidence(
            String status,
            String manifestObjectBucket,
            String manifestObjectKey,
            String manifestSha256) {

        public boolean isFrozenWithManifest() {
            return "FROZEN".equals(status)
                    && manifestObjectBucket != null
                    && manifestObjectKey != null
                    && manifestSha256 != null
                    && manifestSha256.matches("[0-9a-f]{64}");
        }
    }

    record ModelEvidence(
            String approvalState,
            UUID trainingRunId,
            UUID datasetVersionId,
            String registryName,
            String registryVersion,
            UUID registeredBy,
            String sbomSha256,
            String signatureKeyId,
            String evaluationReportSha256,
            String thresholdGateSha256) {

        public boolean isApprovedWithCompleteSupplyChain() {
            return "APPROVED".equals(approvalState)
                    && isCompleteSupplyChain();
        }

        public boolean isCompleteSupplyChain() {
            return trainingRunId != null
                    && datasetVersionId != null
                    && registryName != null
                    && registryVersion != null
                    && registeredBy != null
                    && sbomSha256 != null
                    && signatureKeyId != null
                    && evaluationReportSha256 != null
                    && thresholdGateSha256 != null;
        }
    }
}
