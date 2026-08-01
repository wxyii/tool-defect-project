package com.tooldefect.business.dataset.infrastructure;

import com.tooldefect.business.dataset.application.DatasetQueryRepository;
import com.tooldefect.business.dataset.application.DatasetRepository;
import com.tooldefect.business.dataset.domain.CandidateSample;
import com.tooldefect.business.dataset.domain.CandidateSample.CandidateSampleStatus;
import com.tooldefect.business.dataset.domain.CandidateManifest;
import com.tooldefect.business.dataset.domain.DatasetVersion;
import com.tooldefect.business.dataset.domain.DatasetVersionState;
import com.tooldefect.business.dataset.domain.DatasetNotFound;
import com.tooldefect.business.shared.domain.DomainViolation;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.nio.charset.StandardCharsets;
import java.util.*;

@Repository
public class JdbcDatasetRepository implements DatasetRepository, DatasetQueryRepository {

    private final JdbcTemplate jdbc;

    public JdbcDatasetRepository(JdbcTemplate jdbc) {
        this.jdbc = Objects.requireNonNull(jdbc);
    }

    @Override
    public void insertDataset(
            UUID datasetId,
            String datasetName,
            String purpose,
            Instant createdAt) {
        try {
            jdbc.update(
                """
                INSERT INTO dataset
                (dataset_id, dataset_name, purpose, created_at)
                VALUES (?::uuid, ?, ?, ?)
                """,
                datasetId, datasetName, purpose,
                java.sql.Timestamp.from(createdAt)
            );
        } catch (DuplicateKeyException duplicate) {
            throw new DomainViolation("数据集名称已存在", duplicate);
        }
    }

    @Override
    public Optional<DatasetVersion> findVersion(UUID datasetVersionId) {
        var rows = jdbc.query(
            "SELECT * FROM dataset_version WHERE dataset_version_id = ?::uuid",
            JdbcDatasetRepository::mapVersion, datasetVersionId
        );
        return rows.stream().findFirst();
    }

    @Override
    public Optional<CandidateManifest> findCandidateManifest(UUID candidateManifestId) {
        var rows = jdbc.query(
            "SELECT * FROM dataset_candidate_manifest WHERE candidate_manifest_id = ?::uuid",
            JdbcDatasetRepository::mapCandidateManifest,
            candidateManifestId
        );
        return rows.stream().findFirst();
    }

    @Override
    public void updateCandidateManifest(CandidateManifest manifest) {
        int count = jdbc.update(
            """
            UPDATE dataset_candidate_manifest
            SET approval_state = ?, approved_by = ?::uuid, approved_at = ?
            WHERE candidate_manifest_id = ?::uuid
              AND approval_state = 'REGISTERED'
            """,
            manifest.approvalState().name(),
            manifest.approvedBy(),
            timestamp(manifest.approvedAt()),
            manifest.candidateManifestId()
        );
        if (count != 1) {
            throw new DomainViolation(
                "候选清单审批冲突或不存在: " + manifest.candidateManifestId()
            );
        }
    }

    @Override
    public void insertVersion(DatasetVersion version) {
        jdbc.update(
            """
            INSERT INTO dataset_version
            (dataset_version_id, dataset_id, version, parent_version_id,
             candidate_manifest_id, purpose,
             manifest_object_key, manifest_bucket, manifest_sha256,
             sample_count, stratification, status, approved_by, created_at, approved_at, record_version)
            VALUES (?::uuid, ?::uuid, ?, ?::uuid, ?::uuid, ?, ?, ?, ?, ?, CAST(? AS jsonb), ?, ?::uuid, ?, ?, ?)""",
            version.datasetVersionId(), version.datasetId(), version.version(),
            version.parentVersionId(),
            version.candidateManifestId(), version.purpose(),
            version.manifestObjectKey(), version.manifestObjectBucket(), version.manifestSha256(),
            version.sampleCount(), version.stratificationJson(),
            version.state().name(), version.approvedBy(),
            timestamp(version.createdAt()), timestamp(version.approvedAt()),
            version.recordVersion()
        );
    }

    @Override
    public void updateVersion(DatasetVersion version) {
        int count = jdbc.update(
            """
            UPDATE dataset_version SET
            sample_count = ?, stratification = CAST(? AS jsonb), status = ?,
            approved_by = ?::uuid, approved_at = ?, record_version = ?
            WHERE dataset_version_id = ?::uuid AND record_version = ?""",
            version.sampleCount(), version.stratificationJson(),
            version.state().name(), version.approvedBy(),
            timestamp(version.approvedAt()), version.recordVersion(),
            version.datasetVersionId(), version.recordVersion() - 1
        );
        if (count != 1) {
            throw new DatasetNotFound("数据集版本更新冲突或不存在: " + version.datasetVersionId());
        }
    }

    @Override
    public Optional<DatasetVersion> findLatestVersion(UUID datasetId) {
        var rows = jdbc.query(
            """
            SELECT * FROM dataset_version
            WHERE dataset_id = ?::uuid
            ORDER BY CASE WHEN version ~ '^[0-9]+$' THEN version::numeric ELSE -1 END DESC,
                     created_at DESC, dataset_version_id DESC
            LIMIT 1
            """,
            JdbcDatasetRepository::mapVersion, datasetId
        );
        return rows.stream().findFirst();
    }

    @Override
    public void insertCandidate(CandidateSample candidate) {
        jdbc.update(
            """
            INSERT INTO dataset_candidate_sample
            (candidate_id, capture_id, image_id, mask_image_id,
             label, split, group_key, content_sha256,
             source_review_record_id, status, added_at, approved_at, approved_by)
            VALUES (?::uuid, ?::uuid, ?::uuid, ?::uuid, ?, ?, ?, ?, ?::uuid, ?, ?, ?, ?::uuid)""",
            candidate.candidateId(), candidate.captureId(), candidate.imageId(),
            candidate.maskImageId(), candidate.label(), candidate.split(),
            candidate.groupKey(), candidate.contentSha256(),
            candidate.sourceReviewRecordId(), candidate.status().name(),
            timestamp(candidate.addedAt()), timestamp(candidate.approvedAt()),
            candidate.approvedBy()
        );
    }

    @Override
    public void updateCandidate(CandidateSample candidate) {
        jdbc.update(
            """
            UPDATE dataset_candidate_sample SET status = ?,
            approved_at = ?, approved_by = ?::uuid
            WHERE candidate_id = ?::uuid""",
            candidate.status().name(), timestamp(candidate.approvedAt()),
            candidate.approvedBy(), candidate.candidateId()
        );
    }

    @Override
    public List<CandidateSample> findApprovedCandidates(int limit, int offset) {
        return jdbc.query(
            "SELECT * FROM dataset_candidate_sample WHERE status = 'APPROVED' ORDER BY added_at LIMIT ? OFFSET ?",
            JdbcDatasetRepository::mapCandidate, limit, offset
        );
    }

    @Override
    public List<CandidateSample> findCandidatesByStatus(CandidateSampleStatus status, int limit, int offset) {
        return jdbc.query(
            "SELECT * FROM dataset_candidate_sample WHERE status = ? ORDER BY added_at LIMIT ? OFFSET ?",
            JdbcDatasetRepository::mapCandidate, status.name(), limit, offset
        );
    }

    @Override
    public long countCandidatesByStatus(CandidateSampleStatus status) {
        var result = jdbc.queryForObject(
            "SELECT COUNT(*) FROM dataset_candidate_sample WHERE status = ?",
            Long.class, status.name()
        );
        return result != null ? result : 0L;
    }

    @Override
    public boolean hasSampleHashInVersion(UUID datasetVersionId, String contentSha256) {
        var result = jdbc.queryForObject(
            "SELECT COUNT(*) FROM dataset_sample WHERE dataset_version_id = ?::uuid AND content_sha256 = ?",
            Long.class, datasetVersionId, contentSha256
        );
        return result != null && result > 0;
    }

    @Override
    public List<String> findCrossSplitHashes(UUID datasetVersionId) {
        return jdbc.query(
            """
            SELECT ds.content_sha256
            FROM dataset_sample ds
            WHERE ds.dataset_version_id = ?::uuid
            GROUP BY ds.content_sha256
            HAVING COUNT(DISTINCT ds.split) > 1""",
            (row, rowNumber) -> row.getString("content_sha256"),
            datasetVersionId
        );
    }

    @Override
    public Map<String, Object> listDatasets(
            String actorId, int pageSize, String cursor) {
        List<Object> args = new ArrayList<>();
        StringBuilder sql = new StringBuilder("""
            SELECT d.dataset_id, d.dataset_name, d.purpose, d.created_at,
                   (SELECT COUNT(*) FROM dataset_version counted
                    WHERE counted.dataset_id = d.dataset_id) AS version_count,
                   (SELECT latest.version FROM dataset_version latest
                    WHERE latest.dataset_id = d.dataset_id
                    ORDER BY latest.created_at DESC,
                             latest.dataset_version_id DESC LIMIT 1) AS latest_version,
                   (SELECT latest.status FROM dataset_version latest
                    WHERE latest.dataset_id = d.dataset_id
                    ORDER BY latest.created_at DESC,
                             latest.dataset_version_id DESC LIMIT 1) AS latest_status
            FROM dataset d
            WHERE 1=1
            """);
        if (cursor != null && !cursor.isBlank()) {
            CursorValue decoded = decodeCursor(cursor);
            sql.append("AND (d.created_at, d.dataset_id) < (?, ?::uuid) ");
            args.add(decoded.createdAt());
            args.add(decoded.datasetVersionId());
        }
        sql.append("ORDER BY d.created_at DESC, d.dataset_id DESC LIMIT ?");
        args.add(pageSize + 1);
        List<Map<String, Object>> rows = jdbc.queryForList(
            sql.toString(), args.toArray()
        );
        boolean hasMore = rows.size() > pageSize;
        if (hasMore) rows = rows.subList(0, pageSize);
        List<Map<String, Object>> items = rows.stream()
            .map(JdbcDatasetRepository::datasetSummary)
            .toList();
        String nextCursor = null;
        if (hasMore && !rows.isEmpty()) {
            Map<String, Object> last = rows.get(rows.size() - 1);
            nextCursor = encodeCursor(
                ((java.sql.Timestamp) last.get("created_at")).toInstant(),
                UUID.fromString(String.valueOf(last.get("dataset_id")))
            );
        }
        Map<String, Object> page = new LinkedHashMap<>();
        page.put("items", items);
        page.put("next_cursor", nextCursor);
        page.put("has_more", hasMore);
        return page;
    }

    @Override
    public Map<String, Object> listVersions(
            String actorId,
            UUID datasetId,
            int pageSize,
            String cursor) {
        return listVersions(actorId, datasetId, null, pageSize, cursor);
    }

    @Override
    public Map<String, Object> listVersions(
            String actorId,
            UUID datasetId,
            String status,
            int pageSize,
            String cursor) {
        List<Object> args = new ArrayList<>();
        StringBuilder sql = new StringBuilder("""
            SELECT dv.dataset_version_id, dv.dataset_id, dv.version, dv.status,
                   dv.sample_count, dv.manifest_sha256, dv.created_at
            FROM dataset_version dv
            WHERE 1=1
            """);
        if (datasetId != null) {
            sql.append("AND dv.dataset_id = ?::uuid ");
            args.add(datasetId);
        }
        if (status != null && !status.isBlank()) {
            sql.append("AND dv.status = ? ");
            args.add(status);
        }
        if (cursor != null && !cursor.isBlank()) {
            CursorValue decoded = decodeCursor(cursor);
            sql.append("AND (dv.created_at, dv.dataset_version_id) < (?, ?::uuid) ");
            args.add(decoded.createdAt());
            args.add(decoded.datasetVersionId());
        }
        sql.append("ORDER BY dv.created_at DESC, dv.dataset_version_id DESC LIMIT ?");
        args.add(pageSize + 1);
        List<Map<String, Object>> rows = jdbc.queryForList(sql.toString(), args.toArray());
        boolean hasMore = rows.size() > pageSize;
        if (hasMore) rows = rows.subList(0, pageSize);
        List<Map<String, Object>> items = rows.stream()
            .map(JdbcDatasetRepository::versionSummary)
            .toList();
        String nextCursor = null;
        if (hasMore && !rows.isEmpty()) {
            Map<String, Object> last = rows.get(rows.size() - 1);
            nextCursor = encodeCursor(
                ((java.sql.Timestamp) last.get("created_at")).toInstant(),
                UUID.fromString(String.valueOf(last.get("dataset_version_id")))
            );
        }
        Map<String, Object> page = new LinkedHashMap<>();
        page.put("items", items);
        page.put("next_cursor", nextCursor);
        page.put("has_more", hasMore);
        return page;
    }

    @Override
    public Map<String, Object> detailVersion(String actorId, UUID datasetVersionId) {
        var row = jdbc.queryForMap(
            """
            SELECT dv.*, d.dataset_name
            FROM dataset_version dv JOIN dataset d ON dv.dataset_id = d.dataset_id
            WHERE dv.dataset_version_id = ?::uuid""",
            datasetVersionId
        );
        return row;
    }

    @Override
    public Map<String, Object> listCandidates(String actorId, String statusStr, int pageSize, String cursor) {
        List<Object> args = new ArrayList<>();
        StringBuilder sql = new StringBuilder(
            "SELECT * FROM dataset_candidate_sample WHERE 1=1 ");
        if (statusStr != null && !statusStr.isEmpty()) {
            sql.append("AND status = ? ");
            args.add(statusStr);
        }
        sql.append("ORDER BY added_at DESC LIMIT ?");
        args.add(pageSize + 1);
        List<Map<String, Object>> rows = jdbc.queryForList(sql.toString(), args.toArray());
        boolean hasMore = rows.size() > pageSize;
        if (hasMore) rows = rows.subList(0, pageSize);
        return Map.of("items", rows, "has_more", hasMore);
    }

    @Override
    public Map<String, Object> listCandidateManifests(
            String actorId,
            UUID datasetId,
            String approvalState,
            int pageSize,
            String cursor) {
        List<Object> args = new ArrayList<>();
        StringBuilder sql = new StringBuilder("""
            SELECT candidate_manifest_id, dataset_id, manifest_bucket,
                   manifest_object_key, manifest_sha256, sample_count,
                   approval_state, approved_by, approved_at, created_at
            FROM dataset_candidate_manifest
            WHERE dataset_id = ?::uuid
            """);
        args.add(datasetId);
        if (approvalState != null && !approvalState.isBlank()) {
            sql.append("AND approval_state = ? ");
            args.add(approvalState);
        }
        if (cursor != null && !cursor.isBlank()) {
            CursorValue decoded = decodeCursor(cursor);
            sql.append(
                "AND (created_at, candidate_manifest_id) < (?, ?::uuid) "
            );
            args.add(decoded.createdAt());
            args.add(decoded.datasetVersionId());
        }
        sql.append(
            "ORDER BY created_at DESC, candidate_manifest_id DESC LIMIT ?"
        );
        args.add(pageSize + 1);
        List<Map<String, Object>> rows = jdbc.queryForList(
            sql.toString(), args.toArray()
        );
        boolean hasMore = rows.size() > pageSize;
        if (hasMore) rows = rows.subList(0, pageSize);
        List<Map<String, Object>> items = rows.stream()
            .map(JdbcDatasetRepository::candidateManifestSummary)
            .toList();
        String nextCursor = null;
        if (hasMore && !rows.isEmpty()) {
            Map<String, Object> last = rows.get(rows.size() - 1);
            nextCursor = encodeCursor(
                ((java.sql.Timestamp) last.get("created_at")).toInstant(),
                UUID.fromString(String.valueOf(last.get("candidate_manifest_id")))
            );
        }
        Map<String, Object> page = new LinkedHashMap<>();
        page.put("items", items);
        page.put("next_cursor", nextCursor);
        page.put("has_more", hasMore);
        return page;
    }

    @Override
    public Map<String, Object> diffVersions(UUID fromVersionId, UUID toVersionId) {
        Map<String, Object> from = versionSummaryRow(fromVersionId);
        Map<String, Object> to = versionSummaryRow(toVersionId);
        if (!Objects.equals(from.get("dataset_id"), to.get("dataset_id"))) {
            throw new com.tooldefect.business.shared.domain.DomainViolation(
                "只能比较同一数据集的两个版本"
            );
        }

        Map<String, String> fromSamples = sampleHashes(fromVersionId);
        Map<String, String> toSamples = sampleHashes(toVersionId);
        Set<String> keys = new TreeSet<>();
        keys.addAll(fromSamples.keySet());
        keys.addAll(toSamples.keySet());
        List<Map<String, Object>> details = new ArrayList<>();
        int added = 0;
        int removed = 0;
        int modified = 0;
        int unchanged = 0;
        for (String key : keys) {
            String before = fromSamples.get(key);
            String after = toSamples.get(key);
            String change;
            String summary;
            if (before == null) {
                change = "ADDED";
                summary = "样本只存在于目标版本";
                added++;
            } else if (after == null) {
                change = "REMOVED";
                summary = "样本只存在于基准版本";
                removed++;
            } else if (!before.equals(after)) {
                change = "MODIFIED";
                summary = "内容 SHA-256 发生变化";
                modified++;
            } else {
                change = "UNCHANGED";
                summary = "样本内容未变化";
                unchanged++;
            }
            details.add(Map.of(
                "sample_id", key,
                "change", change,
                "diff_summary", summary
            ));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("from_version", from);
        result.put("to_version", to);
        result.put("added_samples", added);
        result.put("removed_samples", removed);
        result.put("modified_samples", modified);
        result.put("unchanged_samples", unchanged);
        result.put("sample_diff_details", details);
        return result;
    }

    private Map<String, String> sampleHashes(UUID datasetVersionId) {
        Map<String, String> result = new LinkedHashMap<>();
        jdbc.query(
            """
            SELECT sample_key, content_sha256
            FROM dataset_sample
            WHERE dataset_version_id = ?::uuid
            ORDER BY sample_key
            """,
            (row, rowNumber) -> {
                result.put(row.getString("sample_key"), row.getString("content_sha256"));
                return null;
            },
            datasetVersionId
        );
        return result;
    }

    private Map<String, Object> versionSummaryRow(UUID datasetVersionId) {
        try {
            return versionSummary(jdbc.queryForMap(
                """
                SELECT dataset_version_id, dataset_id, version, status, sample_count,
                       manifest_sha256, created_at
                FROM dataset_version
                WHERE dataset_version_id = ?::uuid
                """,
                datasetVersionId
            ));
        } catch (org.springframework.dao.EmptyResultDataAccessException missing) {
            throw new DatasetNotFound(datasetVersionId);
        }
    }

    private static Map<String, Object> versionSummary(Map<String, Object> row) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("version_id", String.valueOf(row.get("dataset_version_id")));
        result.put("dataset_id", String.valueOf(row.get("dataset_id")));
        result.put("version", String.valueOf(row.get("version")));
        result.put("sample_count", ((Number) row.get("sample_count")).intValue());
        result.put("status", String.valueOf(row.get("status")));
        result.put(
            "manifest_sha256",
            row.get("manifest_sha256") != null ? String.valueOf(row.get("manifest_sha256")) : null
        );
        result.put("created_at", ((java.sql.Timestamp) row.get("created_at")).toInstant().toString());
        return result;
    }

    private static Map<String, Object> datasetSummary(
            Map<String, Object> row) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("dataset_id", String.valueOf(row.get("dataset_id")));
        result.put("dataset_name", String.valueOf(row.get("dataset_name")));
        result.put("purpose", String.valueOf(row.get("purpose")));
        result.put(
            "version_count",
            ((Number) row.get("version_count")).intValue()
        );
        result.put(
            "latest_version",
            row.get("latest_version") == null
                ? null : String.valueOf(row.get("latest_version"))
        );
        result.put(
            "latest_status",
            row.get("latest_status") == null
                ? null : String.valueOf(row.get("latest_status"))
        );
        result.put(
            "created_at",
            ((java.sql.Timestamp) row.get("created_at")).toInstant().toString()
        );
        return result;
    }

    private static Map<String, Object> candidateManifestSummary(
            Map<String, Object> row) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put(
            "candidate_manifest_id",
            String.valueOf(row.get("candidate_manifest_id"))
        );
        result.put("dataset_id", String.valueOf(row.get("dataset_id")));
        result.put("manifest_bucket", String.valueOf(row.get("manifest_bucket")));
        result.put(
            "manifest_object_key",
            String.valueOf(row.get("manifest_object_key"))
        );
        result.put("manifest_sha256", String.valueOf(row.get("manifest_sha256")));
        result.put("sample_count", ((Number) row.get("sample_count")).intValue());
        result.put("approval_state", String.valueOf(row.get("approval_state")));
        result.put(
            "approved_by",
            row.get("approved_by") == null
                ? null : String.valueOf(row.get("approved_by"))
        );
        result.put(
            "approved_at",
            row.get("approved_at") == null
                ? null
                : ((java.sql.Timestamp) row.get("approved_at"))
                    .toInstant().toString()
        );
        result.put(
            "created_at",
            ((java.sql.Timestamp) row.get("created_at")).toInstant().toString()
        );
        return result;
    }

    private static String encodeCursor(Instant createdAt, UUID datasetVersionId) {
        String value = createdAt.toString() + "|" + datasetVersionId;
        return Base64.getUrlEncoder().withoutPadding()
            .encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }

    private static CursorValue decodeCursor(String value) {
        try {
            String decoded = new String(
                Base64.getUrlDecoder().decode(value),
                StandardCharsets.UTF_8
            );
            String[] parts = decoded.split("\\|", -1);
            if (parts.length != 2) throw new IllegalArgumentException();
            return new CursorValue(Instant.parse(parts[0]), UUID.fromString(parts[1]));
        } catch (RuntimeException invalid) {
            throw new com.tooldefect.business.shared.api.ContractValues.ContractInputViolation(
                "cursor 不符合数据集版本分页契约",
                invalid
            );
        }
    }

    private record CursorValue(Instant createdAt, UUID datasetVersionId) {}

    private static DatasetVersion mapVersion(ResultSet rs, int rowNum) throws SQLException {
        return new DatasetVersion(
            uuid(rs, "dataset_version_id"),
            uuid(rs, "dataset_id"),
            rs.getString("version"),
            uuid(rs, "parent_version_id"),
            uuid(rs, "candidate_manifest_id"),
            rs.getString("purpose"),
            rs.getString("manifest_object_key"),
            rs.getString("manifest_bucket"),
            rs.getString("manifest_sha256"),
            rs.getInt("sample_count"),
            rs.getString("stratification"),
            DatasetVersionState.valueOf(rs.getString("status")),
            uuid(rs, "approved_by"),
            rs.getTimestamp("created_at").toInstant(),
            rs.getTimestamp("approved_at") != null ? rs.getTimestamp("approved_at").toInstant() : null,
            rs.getInt("record_version")
        );
    }

    private static CandidateManifest mapCandidateManifest(ResultSet rs, int rowNum)
            throws SQLException {
        return new CandidateManifest(
            uuid(rs, "candidate_manifest_id"),
            uuid(rs, "dataset_id"),
            rs.getString("manifest_bucket"),
            rs.getString("manifest_object_key"),
            rs.getString("manifest_sha256"),
            rs.getInt("sample_count"),
            CandidateManifest.ApprovalState.valueOf(rs.getString("approval_state")),
            uuid(rs, "approved_by"),
            rs.getTimestamp("approved_at") != null
                ? rs.getTimestamp("approved_at").toInstant() : null,
            rs.getTimestamp("created_at").toInstant()
        );
    }

    private static CandidateSample mapCandidate(ResultSet rs, int rowNum) throws SQLException {
        return new CandidateSample(
            uuid(rs, "candidate_id"),
            uuid(rs, "capture_id"),
            uuid(rs, "image_id"),
            uuid(rs, "mask_image_id"),
            rs.getString("label"),
            rs.getString("split"),
            rs.getString("group_key"),
            rs.getString("content_sha256"),
            uuid(rs, "source_review_record_id"),
            CandidateSampleStatus.valueOf(rs.getString("status")),
            rs.getTimestamp("added_at").toInstant(),
            rs.getTimestamp("approved_at") != null ? rs.getTimestamp("approved_at").toInstant() : null,
            uuid(rs, "approved_by")
        );
    }

    private static UUID uuid(ResultSet rs, String column) throws SQLException {
        String value = rs.getString(column);
        return value != null ? UUID.fromString(value) : null;
    }

    private static java.sql.Timestamp timestamp(Instant value) {
        return value == null ? null : java.sql.Timestamp.from(value);
    }
}
