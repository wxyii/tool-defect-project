package com.tooldefect.business.dataset.application;

import com.tooldefect.business.dataset.domain.CandidateSample;
import com.tooldefect.business.dataset.domain.CandidateManifest;
import com.tooldefect.business.dataset.domain.DatasetVersion;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

public interface DatasetRepository {

    Optional<DatasetVersion> findVersion(UUID datasetVersionId);

    Optional<CandidateManifest> findCandidateManifest(UUID candidateManifestId);

    void insertVersion(DatasetVersion version);

    void updateVersion(DatasetVersion version);

    Optional<DatasetVersion> findLatestVersion(UUID datasetId);

    void insertCandidate(CandidateSample candidate);

    void updateCandidate(CandidateSample candidate);

    List<CandidateSample> findApprovedCandidates(int limit, int offset);

    List<CandidateSample> findCandidatesByStatus(CandidateSample.CandidateSampleStatus status, int limit, int offset);

    long countCandidatesByStatus(CandidateSample.CandidateSampleStatus status);

    boolean hasSampleHashInVersion(UUID datasetVersionId, String contentSha256);

    List<String> findCrossSplitHashes(UUID datasetVersionId);

    record VersionSummary(UUID datasetVersionId, String version, String state,
                          int sampleCount, String manifestSha256,
                          java.time.Instant createdAt) {}
}
