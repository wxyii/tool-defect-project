package com.tooldefect.business.detection.application;

import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.OptionalDouble;
import java.util.UUID;

public record DetectionResultSubmission(
        UUID captureId,
        UUID detectionTaskId,
        UUID attemptId,
        String schemaVersion,
        String algorithmOutcome,
        OptionalDouble confidence,
        double qualifiedProbability,
        double unqualifiedProbability,
        String preprocessQuality,
        String modelVersion,
        String modelSha256,
        List<Region> regions,
        List<DerivedArtifact> artifacts,
        List<String> warnings,
        Map<String, Object> timings,
        Map<String, Object> raw) {

    public DetectionResultSubmission {
        Objects.requireNonNull(captureId);
        Objects.requireNonNull(detectionTaskId);
        Objects.requireNonNull(attemptId);
        Objects.requireNonNull(confidence);
        regions = List.copyOf(regions);
        artifacts = List.copyOf(artifacts);
        warnings = List.copyOf(warnings);
        timings = Map.copyOf(timings);
        raw = java.util.Collections.unmodifiableMap(
            new java.util.LinkedHashMap<>(raw)
        );
    }

    public record Region(
        int regionNumber,
        String coordinateSpace,
        String geometryType,
        Map<String, Object> geometry,
        Map<String, Object> scores,
        Map<String, Object> attributes
    ) {
        public Region {
            geometry = Map.copyOf(geometry);
            scores = Map.copyOf(scores);
            attributes = java.util.Collections.unmodifiableMap(
                new java.util.LinkedHashMap<>(attributes)
            );
        }
    }

    public record DerivedArtifact(
        UUID imageId,
        String kind,
        String bucket,
        String objectKey,
        String objectVersion,
        String sha256,
        long sizeBytes,
        String mediaType
    ) {}
}
