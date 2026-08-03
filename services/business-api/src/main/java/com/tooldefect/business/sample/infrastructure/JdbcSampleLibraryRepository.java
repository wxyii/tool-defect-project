package com.tooldefect.business.sample.infrastructure;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import com.tooldefect.business.sample.application.SampleCursor;
import com.tooldefect.business.sample.application.SampleLibraryRepository;
import com.tooldefect.business.sample.application.SampleViolation;
import com.tooldefect.business.shared.application.CanonicalJson;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@Repository
public class JdbcSampleLibraryRepository implements SampleLibraryRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;

    public JdbcSampleLibraryRepository(JdbcTemplate jdbc, ObjectMapper json) {
        this.jdbc = java.util.Objects.requireNonNull(jdbc);
        this.json = java.util.Objects.requireNonNull(json);
    }

    @Override
    public List<AdminDetectionItem> listAdminDetectionItems(
            String label, String status, String usageStage, String cursor, int limit) {
        SampleCursor.Boundary boundary = decodeCursor(cursor);
        StringBuilder sql = new StringBuilder("""
            SELECT i.batch_item_id, i.batch_id, o.bucket, o.object_key,
              o.object_version, o.sha256, o.size_bytes, o.media_type,
              i.status, i.algorithm_outcome, i.quick_review_decision,
              b.usage_stage, i.created_at, i.updated_at,
              af.feedback_id, af.label AS admin_label, af.note AS admin_note,
              af.source_review_record_id, af.supersedes_feedback_id,
              af.revision_no, af.submitted_by AS admin_submitted_by,
              af.submitted_at AS admin_submitted_at,
              employee.decision AS employee_decision
            FROM detection_batch_item_v2 i
            JOIN detection_batch_v2 b ON b.batch_id = i.batch_id
            JOIN image_object o ON o.image_id = i.image_id
            LEFT JOIN LATERAL (
              SELECT feedback_id, label, note, source_review_record_id,
                     supersedes_feedback_id, revision_no, submitted_by, submitted_at
              FROM admin_feedback_v2
              WHERE batch_item_id = i.batch_item_id
              ORDER BY revision_no DESC, submitted_at DESC, feedback_id DESC
              LIMIT 1
            ) af ON true
            LEFT JOIN LATERAL (
              SELECT decision
              FROM quick_feedback_v2
              WHERE batch_item_id = i.batch_item_id
              ORDER BY submitted_at DESC, feedback_id DESC
              LIMIT 1
            ) employee ON true
            WHERE 1 = 1
            """);
        List<Object> args = new ArrayList<>();
        if (label != null) {
            sql.append(" AND af.label = ?");
            args.add(label);
        }
        if (status != null) {
            sql.append(" AND i.status = ?");
            args.add(status);
        }
        if (usageStage != null) {
            sql.append(" AND b.usage_stage = ?");
            args.add(usageStage);
        }
        if (boundary != null) {
            sql.append(" AND (i.created_at, i.batch_item_id) < (?, ?)");
            args.add(Timestamp.from(boundary.createdAt()));
            args.add(boundary.id());
        }
        sql.append(" ORDER BY i.created_at DESC, i.batch_item_id DESC LIMIT ?");
        args.add(limit + 1);
        return jdbc.query(sql.toString(), JdbcSampleLibraryRepository::adminItem,
            args.toArray());
    }

    @Override
    @Transactional
    public FeedbackRecord appendAdminFeedback(
            UUID feedbackId, UUID itemId, UUID actorId, String label, String note,
            UUID sourceReviewRecordId, UUID supersedesFeedbackId, String idempotencyKey) {
        List<FeedbackRecord> current = jdbc.query("""
            SELECT feedback_id,batch_item_id,label,note,source_review_record_id,
              supersedes_feedback_id,revision_no,submitted_by,submitted_at
            FROM admin_feedback_v2
            WHERE batch_item_id = ?
            ORDER BY revision_no DESC, submitted_at DESC, feedback_id DESC
            LIMIT 1 FOR UPDATE
            """, (row, number) -> feedback(row), itemId);
        FeedbackRecord latest = current.isEmpty() ? null : current.getFirst();
        int revision;
        if (latest == null) {
            if (supersedesFeedbackId != null) {
                throw violation(SampleViolation.Kind.CONFLICT, "首次管理员反馈不能引用修订记录");
            }
            revision = 1;
        } else {
            if (supersedesFeedbackId == null
                    || !latest.feedbackId().equals(supersedesFeedbackId)) {
                throw violation(SampleViolation.Kind.CONFLICT,
                    "管理员反馈修订必须基于当前最新记录");
            }
            revision = latest.revision() + 1;
        }
        ensureItemExists(itemId);
        try {
            jdbc.update("""
                INSERT INTO admin_feedback_v2(
                  feedback_id,batch_item_id,label,note,source_review_record_id,
                  submitted_by,idempotency_key,supersedes_feedback_id,revision_no)
                VALUES (?,?,?,?,?,?,?,?,?)
                """, feedbackId, itemId, label, note, sourceReviewRecordId,
                actorId, idempotencyKey, supersedesFeedbackId, revision);
        } catch (DuplicateKeyException conflict) {
            throw violation(SampleViolation.Kind.CONFLICT, "管理员反馈幂等键或修订记录冲突");
        }
        return jdbc.query("""
            SELECT feedback_id,batch_item_id,label,note,source_review_record_id,
              supersedes_feedback_id,revision_no,submitted_by,submitted_at
            FROM admin_feedback_v2 WHERE feedback_id = ?
            """, (row, number) -> feedback(row), feedbackId).getFirst();
    }

    @Override
    @Transactional
    public Candidate createCandidate(UUID candidateId, UUID itemId, UUID feedbackId) {
        Snapshot snapshot = loadSnapshot(itemId, feedbackId);
        try {
            jdbc.update("""
                INSERT INTO sample_candidate_v2(
                  sample_candidate_id,batch_item_id,feedback_id,status,
                  source_snapshot,source_snapshot_sha256)
                VALUES (?, ?, ?, 'PENDING', CAST(? AS jsonb), ?)
                ON CONFLICT (batch_item_id, feedback_id) DO NOTHING
                """, candidateId, itemId, feedbackId, snapshot.json(), snapshot.sha256());
        } catch (DuplicateKeyException conflict) {
            throw violation(SampleViolation.Kind.CONFLICT, "样本候选来源约束冲突");
        }
        return findCandidateByItemAndFeedback(itemId, feedbackId)
            .orElseThrow(() -> violation(SampleViolation.Kind.HOLD,
                "样本候选写入后无法重新读取事实"));
    }

    @Override
    public List<Candidate> listCandidates(String status, String cursor, int limit) {
        SampleCursor.Boundary boundary = decodeCursor(cursor);
        StringBuilder sql = new StringBuilder("""
            SELECT c.sample_candidate_id,c.batch_item_id,c.feedback_id,c.status,
              c.decision_note,c.source_snapshot::text,c.latest_decision_id,
              exported.sample_export_job_id,c.created_at
            FROM sample_candidate_v2 c
            LEFT JOIN LATERAL (
              SELECT sample_export_job_id
              FROM sample_export_item_v2
              WHERE sample_candidate_id = c.sample_candidate_id
              ORDER BY created_at DESC, sample_export_job_id DESC
              LIMIT 1
            ) exported ON true
            WHERE 1 = 1
            """);
        List<Object> args = new ArrayList<>();
        if (status != null) {
            sql.append(" AND c.status = ?");
            args.add(status);
        }
        if (boundary != null) {
            sql.append(" AND (c.created_at, c.sample_candidate_id) < (?, ?)");
            args.add(Timestamp.from(boundary.createdAt()));
            args.add(boundary.id());
        }
        sql.append(" ORDER BY c.created_at DESC, c.sample_candidate_id DESC LIMIT ?");
        args.add(limit + 1);
        return jdbc.query(sql.toString(), JdbcSampleLibraryRepository::candidate,
            args.toArray());
    }

    @Override
    @Transactional
    public Candidate decideCandidate(
            UUID candidateId, UUID actorId, String decision, String note,
            UUID supersedesDecisionId) {
        Candidate current = findCandidateForUpdate(candidateId)
            .orElseThrow(() -> violation(SampleViolation.Kind.NOT_FOUND, "样本候选不存在"));
        if ("EXPORTED".equals(current.status())) {
            throw violation(SampleViolation.Kind.CONFLICT, "已导出的样本候选不可再修改纳入状态");
        }
        if (current.latestDecisionId() == null) {
            if (supersedesDecisionId != null) {
                throw violation(SampleViolation.Kind.CONFLICT, "首次候选决策不能引用修订记录");
            }
        } else if (!current.latestDecisionId().equals(supersedesDecisionId)) {
            throw violation(SampleViolation.Kind.CONFLICT, "候选决策修订必须基于当前最新记录");
        }
        UUID decisionId = UUID.randomUUID();
        try {
            jdbc.update("""
                INSERT INTO sample_candidate_decision_v2(
                  decision_id,sample_candidate_id,decision,decision_note,
                  supersedes_decision_id,decided_by)
                VALUES (?,?,?,?,?,?)
                """, decisionId, candidateId, decision, note,
                supersedesDecisionId, actorId);
        } catch (DuplicateKeyException conflict) {
            throw violation(SampleViolation.Kind.CONFLICT, "候选决策修订记录冲突");
        }
        String status = "INCLUDE".equals(decision) ? "INCLUDED" : "EXCLUDED";
        jdbc.update("""
            UPDATE sample_candidate_v2
            SET status = ?, decision_note = ?, decided_by = ?, decided_at = now(),
                latest_decision_id = ?, included_at = CASE WHEN ? THEN now() ELSE NULL END,
                record_version = record_version + 1
            WHERE sample_candidate_id = ? AND status <> 'EXPORTED'
            """, status, note, actorId, decisionId, "INCLUDED".equals(status), candidateId);
        return findCandidate(candidateId).orElseThrow(() -> violation(SampleViolation.Kind.HOLD,
            "候选决策写入后无法重新读取事实"));
    }

    @Override
    @Transactional
    public ExportJob createExportJob(
            UUID jobId, UUID actorId, List<UUID> candidateIds,
            Map<String, String> filterSnapshot, String packageBucket, String packageKey,
            Instant expiresAt) {
        String placeholders = String.join(",", java.util.Collections.nCopies(candidateIds.size(), "?"));
        List<Object> ids = new ArrayList<>(candidateIds);
        List<Candidate> selected = jdbc.query("""
            SELECT sample_candidate_id,batch_item_id,feedback_id,status,decision_note,
              source_snapshot::text,latest_decision_id,NULL::uuid,created_at
            FROM sample_candidate_v2
            WHERE sample_candidate_id IN (""" + placeholders + ") ORDER BY sample_candidate_id FOR UPDATE",
            JdbcSampleLibraryRepository::candidate, ids.toArray());
        if (selected.size() != candidateIds.size()) {
            throw violation(SampleViolation.Kind.NOT_FOUND, "一个或多个样本候选不存在");
        }
        if (selected.stream().anyMatch(candidate -> !"INCLUDED".equals(candidate.status()))) {
            throw violation(SampleViolation.Kind.CONFLICT, "导出只能包含已纳入的样本候选");
        }
        String filterJson = CanonicalJson.encode(filterSnapshot);
        jdbc.update("""
            INSERT INTO sample_export_job_v2(
              sample_export_job_id,filter_snapshot,candidate_count,status,
              package_bucket,package_object_key,package_media_type,requested_by,expires_at)
            VALUES (?,CAST(? AS jsonb),?,'QUEUED',?,?, 'application/zip',?,?)
            """, jobId, filterJson, selected.size(), packageBucket, packageKey,
            actorId, Timestamp.from(expiresAt));
        for (Candidate candidate : selected) {
            jdbc.update("""
                INSERT INTO sample_export_item_v2(
                  sample_export_job_id,sample_candidate_id,status,source_snapshot)
                VALUES (?,?,'QUEUED',CAST(? AS jsonb))
                """, jobId, candidate.candidateId(), candidate.sourceSnapshot());
        }
        return findExportJob(jobId).orElseThrow(() -> violation(SampleViolation.Kind.HOLD,
            "导出作业写入后无法重新读取事实"));
    }

    @Override
    @Transactional
    public void applyExportCompleted(
            UUID jobId, ObjectReference packageReference, ObjectReference manifestReference,
            int exportedCount, List<UUID> failedCandidateIds) {
        ExportProjection current = jdbc.query("""
            SELECT sample_export_job_id,candidate_count,status,package_bucket,
              package_object_key,exported_count,failure_count,package_sha256,
              package_size_bytes,manifest_sha256,manifest_size_bytes,
              failed_candidate_ids::text
            FROM sample_export_job_v2
            WHERE sample_export_job_id = ?
            FOR UPDATE
            """, (row, number) -> new ExportProjection(
                row.getObject("sample_export_job_id", UUID.class),
                row.getInt("candidate_count"), row.getString("status"),
                row.getString("package_bucket"), row.getString("package_object_key"),
                row.getInt("exported_count"), row.getInt("failure_count"),
                row.getString("package_sha256"), row.getObject("package_size_bytes", Long.class),
                row.getString("manifest_sha256"), row.getObject("manifest_size_bytes", Long.class),
                row.getString("failed_candidate_ids")), jobId).stream().findFirst()
            .orElseThrow(() -> violation(SampleViolation.Kind.NOT_FOUND, "样本导出作业不存在"));

        List<UUID> failed = failedCandidateIds.stream().distinct().sorted().toList();
        String failedJson = CanonicalJson.encode(failed.stream().map(UUID::toString).toList());
        if (current.terminal()) {
            if (!current.matches(packageReference, manifestReference, exportedCount, failedJson)) {
                throw violation(SampleViolation.Kind.CONFLICT, "样本导出完成事件与既有终态冲突");
            }
            return;
        }
        if (!Set.of("QUEUED", "RUNNING").contains(current.status())) {
            throw violation(SampleViolation.Kind.CONFLICT, "样本导出作业当前状态不允许完成");
        }
        if (!Objects.equals(current.packageBucket(), packageReference.bucket())
                || !Objects.equals(current.packageKey(), packageReference.objectKey())) {
            throw violation(SampleViolation.Kind.INTEGRITY, "完成事件压缩包位置与请求不一致");
        }
        List<UUID> candidateIds = jdbc.query("""
            SELECT sample_candidate_id
            FROM sample_export_item_v2
            WHERE sample_export_job_id = ?
            ORDER BY sample_candidate_id
            FOR UPDATE
            """, (row, number) -> row.getObject("sample_candidate_id", UUID.class), jobId);
        if (candidateIds.size() != current.candidateCount()
                || exportedCount < 0
                || exportedCount + failed.size() != current.candidateCount()
                || !candidateIds.containsAll(failed)) {
            throw violation(SampleViolation.Kind.INTEGRITY,
                "样本导出完成计数或候选集合不一致");
        }
        Set<UUID> failedSet = Set.copyOf(failed);
        List<UUID> exportedIds = candidateIds.stream()
            .filter(candidateId -> !failedSet.contains(candidateId))
            .toList();
        if (exportedIds.size() != exportedCount) {
            throw violation(SampleViolation.Kind.INTEGRITY, "样本导出成功数量与候选集合不一致");
        }
        for (UUID candidateId : failed) {
            requireItemState(jobId, candidateId, "FAILED");
            jdbc.update("""
                UPDATE sample_export_item_v2
                SET status='FAILED', error_code='EXPORT_ITEM_FAILED',
                    error_detail='worker 清单标记候选失败', updated_at=now(),
                    record_version=record_version+1
                WHERE sample_export_job_id=? AND sample_candidate_id=?
                """, jobId, candidateId);
        }
        for (UUID candidateId : exportedIds) {
            requireItemState(jobId, candidateId, "EXPORTED");
            jdbc.update("""
                UPDATE sample_export_item_v2
                SET status='EXPORTED', exported_sha256=?, exported_size_bytes=?,
                    error_code=NULL, error_detail=NULL, updated_at=now(),
                    record_version=record_version+1
                WHERE sample_export_job_id=? AND sample_candidate_id=?
                """, packageReference.sha256(), packageReference.sizeBytes(), jobId, candidateId);
            int candidateUpdated = jdbc.update("""
                UPDATE sample_candidate_v2
                SET status='EXPORTED', exported_at=now(), record_version=record_version+1
                WHERE sample_candidate_id=? AND status='INCLUDED'
                """, candidateId);
            if (candidateUpdated != 1) {
                throw violation(SampleViolation.Kind.CONFLICT,
                    "样本候选当前状态不允许标记为已导出");
            }
        }
        String status = failed.isEmpty() ? "SUCCEEDED" : "FAILED";
        jdbc.update("""
            UPDATE sample_export_job_v2
            SET status=?, exported_count=?, failure_count=?,
                package_object_version=?, package_sha256=?, package_size_bytes=?, package_media_type=?,
                manifest_bucket=?, manifest_object_key=?, manifest_object_version=?,
                manifest_sha256=?, manifest_size_bytes=?, failed_candidate_ids=?::jsonb,
                record_version=record_version+1
            WHERE sample_export_job_id=?
            """, status, exportedCount, failed.size(), packageReference.objectVersion(),
            packageReference.sha256(), packageReference.sizeBytes(), packageReference.mediaType(),
            manifestReference.bucket(),
            manifestReference.objectKey(), manifestReference.objectVersion(), manifestReference.sha256(),
            manifestReference.sizeBytes(), failedJson, jobId);
    }

    @Override
    public Optional<ExportJob> findExportJob(UUID jobId) {
        List<ExportJob> jobs = jdbc.query("""
            SELECT sample_export_job_id,filter_snapshot::text,candidate_count,
              exported_count,failure_count,status,package_bucket,package_object_key,
              package_object_version,package_sha256,package_size_bytes,package_media_type,
              manifest_bucket,manifest_object_key,manifest_object_version,
              manifest_sha256,manifest_size_bytes,'application/json' AS manifest_media_type,
              created_at,expires_at
            FROM sample_export_job_v2 WHERE sample_export_job_id = ?
            """, this::exportJob, jobId);
        if (jobs.isEmpty()) {
            return Optional.empty();
        }
        ExportJob job = jobs.getFirst();
        List<UUID> failed = jdbc.query("""
            SELECT sample_candidate_id FROM sample_export_item_v2
            WHERE sample_export_job_id = ? AND status = 'FAILED'
            ORDER BY sample_candidate_id
            """, (row, number) -> row.getObject("sample_candidate_id", UUID.class), jobId);
        List<UUID> candidates = jdbc.query("""
            SELECT sample_candidate_id FROM sample_export_item_v2
            WHERE sample_export_job_id = ?
            ORDER BY sample_candidate_id
            """, (row, number) -> row.getObject("sample_candidate_id", UUID.class), jobId);
        List<ExternalReceipt> receipts = jdbc.query("""
            SELECT receipt_id,sample_export_job_id,receiver_name,external_reference,
              receipt_note,recorded_by,recorded_at
            FROM sample_external_receipt_v2
            WHERE sample_export_job_id = ?
            ORDER BY recorded_at, receipt_id
            """, JdbcSampleLibraryRepository::externalReceipt, jobId);
        return Optional.of(new ExportJob(
            job.jobId(), job.filterSnapshot(), job.candidateCount(), job.exportedCount(),
            job.failedCount(), job.status(), job.packageReference(), job.manifestReference(),
            List.copyOf(failed), job.createdAt(), job.expiresAt(), List.copyOf(candidates),
            job.packageBucket(), job.packageKey(), List.copyOf(receipts)));
    }

    @Override
    @Transactional
    public ExternalReceipt appendExternalReceipt(
            UUID receiptId, UUID jobId, String receiverName,
            String externalReference, String receiptNote, UUID actorId) {
        List<ReceiptEligibility> eligibility = jdbc.query("""
            SELECT status,package_sha256,package_size_bytes
            FROM sample_export_job_v2
            WHERE sample_export_job_id = ?
            FOR UPDATE
            """, (row, number) -> new ReceiptEligibility(
                row.getString("status"), row.getString("package_sha256"),
                row.getObject("package_size_bytes", Long.class)), jobId);
        if (eligibility.isEmpty()) {
            throw violation(SampleViolation.Kind.NOT_FOUND, "样本导出作业不存在");
        }
        ReceiptEligibility state = eligibility.getFirst();
        if (!Set.of("SUCCEEDED", "FAILED").contains(state.status())
                || state.packageSha256() == null || state.packageSizeBytes() == null) {
            throw violation(SampleViolation.Kind.CONFLICT, "导出作业尚无可登记回执的完整对象");
        }
        try {
            jdbc.update("""
                INSERT INTO sample_external_receipt_v2(
                  receipt_id,sample_export_job_id,receiver_name,external_reference,
                  receipt_note,recorded_by)
                VALUES (?,?,?,?,?,?)
                """, receiptId, jobId, receiverName, externalReference, receiptNote, actorId);
        } catch (DuplicateKeyException conflict) {
            throw violation(SampleViolation.Kind.CONFLICT, "外部接收回执重复");
        }
        return jdbc.query("""
            SELECT receipt_id,sample_export_job_id,receiver_name,external_reference,
              receipt_note,recorded_by,recorded_at
            FROM sample_external_receipt_v2
            WHERE receipt_id = ?
            """, JdbcSampleLibraryRepository::externalReceipt, receiptId).stream().findFirst()
            .orElseThrow(() -> violation(SampleViolation.Kind.HOLD,
                "外部接收回执写入后无法重新读取事实"));
    }

    @Override
    @Transactional
    public DownloadTicket issueDownloadTicket(
            UUID ticketId, UUID jobId, String tokenHash, UUID actorId,
            Instant issuedAt, Instant expiresAt, String downloadUrl, String requestId) {
        try {
            jdbc.update("""
                INSERT INTO sample_download_ticket_v2(
                  ticket_id,sample_export_job_id,token_hash,issued_by,issued_at,expires_at)
                VALUES (?,?,?,?,?,?)
                """, ticketId, jobId, tokenHash, actorId, Timestamp.from(issuedAt),
                Timestamp.from(expiresAt));
            jdbc.update("""
                INSERT INTO sample_download_event_v2(
                  download_event_id,ticket_id,sample_export_job_id,actor_id,outcome,request_id)
                VALUES (gen_random_uuid(),?,?,?,'ISSUED',?)
                """, ticketId, jobId, actorId, requestId);
        } catch (DuplicateKeyException conflict) {
            throw violation(SampleViolation.Kind.CONFLICT, "下载票据重复");
        }
        return new DownloadTicket(ticketId, jobId, expiresAt, downloadUrl);
    }

    @Override
    @Transactional
    public void expireDownloadTickets(Instant now, String requestId) {
        List<UUID> expired = jdbc.query("""
            SELECT ticket_id FROM sample_download_ticket_v2
            WHERE status = 'ACTIVE' AND expires_at <= ?
            ORDER BY expires_at, ticket_id
            FOR UPDATE SKIP LOCKED
            """, (row, number) -> row.getObject("ticket_id", UUID.class), Timestamp.from(now));
        for (UUID ticketId : expired) {
            jdbc.update("""
                UPDATE sample_download_ticket_v2
                SET status = 'EXPIRED'
                WHERE ticket_id = ? AND status = 'ACTIVE'
                """, ticketId);
            UUID jobId = jdbc.queryForObject("""
                SELECT sample_export_job_id FROM sample_download_ticket_v2 WHERE ticket_id = ?
                """, UUID.class, ticketId);
            jdbc.update("""
                INSERT INTO sample_download_event_v2(
                  download_event_id,ticket_id,sample_export_job_id,actor_id,outcome,request_id)
                VALUES (gen_random_uuid(),?,?,NULL,'EXPIRED',?)
                """, ticketId, jobId, requestId);
        }
    }

    private Snapshot loadSnapshot(UUID itemId, UUID feedbackId) {
        List<Snapshot> values = jdbc.query("""
            SELECT snapshot::text AS snapshot
            FROM (
              SELECT jsonb_build_object(
                'snapshot_version','r7/1',
                'batch_item_id',i.batch_item_id::text,
                'item_status',i.status,
                'algorithm_outcome',i.algorithm_outcome,
                'image',jsonb_build_object(
                  'bucket',o.bucket,'object_key',o.object_key,
                  'object_version',o.object_version,'sha256',trim(o.sha256),
                  'size_bytes',o.size_bytes,'media_type',o.media_type),
                'employee_feedback',(SELECT jsonb_build_object(
                  'feedback_id',q.feedback_id::text,'decision',q.decision,
                  'submitted_by',q.submitted_by::text,'submitted_at',q.submitted_at)
                  FROM quick_feedback_v2 q WHERE q.batch_item_id=i.batch_item_id
                  ORDER BY q.submitted_at DESC,q.feedback_id DESC LIMIT 1),
                'admin_feedback',(SELECT jsonb_build_object(
                  'feedback_id',a.feedback_id::text,'label',a.label,'note',a.note,
                  'source_review_record_id',a.source_review_record_id::text,
                  'submitted_by',a.submitted_by::text,'submitted_at',a.submitted_at,
                  'revision',a.revision_no)
                  FROM admin_feedback_v2 a
                  WHERE a.feedback_id=? AND a.batch_item_id=i.batch_item_id),
                'quality',(SELECT jsonb_build_object(
                  'overall',q.overall,'checker_version',q.checker_version,
                  'checks',COALESCE((SELECT jsonb_agg(jsonb_build_object(
                    'check_type',c.check_type,'status',c.status,'rule_id',c.rule_id,
                    'reason_code',c.reason_code,'user_hint',c.user_hint,
                    'measurement',c.measurement,'threshold',c.threshold)
                    ORDER BY c.check_type)
                    FROM image_quality_check_v2 c
                    WHERE c.quality_result_id=q.quality_result_id),'[]'::jsonb))
                  FROM image_quality_result_v2 q
                  WHERE q.batch_item_id=i.batch_item_id
                  ORDER BY q.created_at DESC LIMIT 1),
                'result_reference',(SELECT CASE WHEN r.result_bucket IS NULL THEN NULL
                  ELSE jsonb_build_object(
                    'bucket',r.result_bucket,'object_key',r.result_object_key,
                    'object_version',r.result_object_version,
                    'sha256',trim(r.result_sha256),'size_bytes',r.result_size_bytes,
                    'media_type','application/json') END
                  FROM detection_item_result_v2 r
                  WHERE r.batch_item_id=i.batch_item_id),
                'detection_updated_at',i.updated_at
              ) AS snapshot
              FROM detection_batch_item_v2 i
              JOIN image_object o ON o.image_id=i.image_id
              JOIN admin_feedback_v2 feedback
                ON feedback.feedback_id=? AND feedback.batch_item_id=i.batch_item_id
              WHERE i.batch_item_id=?
            ) source
            """, (row, number) -> new Snapshot(row.getString("snapshot"), null),
            feedbackId, feedbackId, itemId);
        if (values.isEmpty()) {
            throw violation(SampleViolation.Kind.NOT_FOUND, "图片项或管理员反馈不存在");
        }
        Snapshot raw = values.getFirst();
        return new Snapshot(raw.json(), sha256(raw.json()));
    }

    private void ensureItemExists(UUID itemId) {
        Integer count = jdbc.queryForObject("""
            SELECT count(*) FROM detection_batch_item_v2 WHERE batch_item_id = ?
            """, Integer.class, itemId);
        if (count == null || count != 1) {
            throw violation(SampleViolation.Kind.NOT_FOUND, "检测图片项不存在");
        }
    }

    private Optional<Candidate> findCandidate(UUID candidateId) {
        return jdbc.query("""
            SELECT c.sample_candidate_id,c.batch_item_id,c.feedback_id,c.status,
              c.decision_note,c.source_snapshot::text,c.latest_decision_id,
              exported.sample_export_job_id,c.created_at
            FROM sample_candidate_v2 c
            LEFT JOIN LATERAL (
              SELECT sample_export_job_id FROM sample_export_item_v2
              WHERE sample_candidate_id=c.sample_candidate_id
              ORDER BY created_at DESC,sample_export_job_id DESC LIMIT 1
            ) exported ON true
            WHERE c.sample_candidate_id = ?
            """, JdbcSampleLibraryRepository::candidate, candidateId).stream().findFirst();
    }

    private Optional<Candidate> findCandidateForUpdate(UUID candidateId) {
        return jdbc.query("""
            SELECT sample_candidate_id,batch_item_id,feedback_id,status,decision_note,
              source_snapshot::text,latest_decision_id,NULL::uuid,created_at
            FROM sample_candidate_v2
            WHERE sample_candidate_id = ? FOR UPDATE
            """, JdbcSampleLibraryRepository::candidate, candidateId).stream().findFirst();
    }

    private Optional<Candidate> findCandidateByItemAndFeedback(UUID itemId, UUID feedbackId) {
        return jdbc.query("""
            SELECT sample_candidate_id,batch_item_id,feedback_id,status,decision_note,
              source_snapshot::text,latest_decision_id,NULL::uuid,created_at
            FROM sample_candidate_v2
            WHERE batch_item_id = ? AND feedback_id = ?
            """, JdbcSampleLibraryRepository::candidate, itemId, feedbackId).stream().findFirst();
    }

    private void requireItemState(UUID jobId, UUID candidateId, String desired) {
        String current = jdbc.query("""
            SELECT status FROM sample_export_item_v2
            WHERE sample_export_job_id=? AND sample_candidate_id=?
            FOR UPDATE
            """, (row, number) -> row.getString("status"), jobId, candidateId)
            .stream().findFirst()
            .orElseThrow(() -> violation(SampleViolation.Kind.INTEGRITY, "导出项不存在"));
        if (!"QUEUED".equals(current)) {
            throw violation(SampleViolation.Kind.CONFLICT, "导出项已处理或状态未知");
        }
    }

    private static AdminDetectionItem adminItem(ResultSet row, int number)
            throws SQLException {
        UUID feedbackId = row.getObject("feedback_id", UUID.class);
        FeedbackRecord feedback = feedbackId == null ? null : new FeedbackRecord(
            feedbackId, row.getObject("batch_item_id", UUID.class),
            row.getString("admin_label"), row.getString("admin_note"),
            row.getObject("source_review_record_id", UUID.class),
            row.getObject("supersedes_feedback_id", UUID.class),
            row.getInt("revision_no"), row.getObject("admin_submitted_by", UUID.class),
            row.getTimestamp("admin_submitted_at").toInstant());
        return new AdminDetectionItem(
            row.getObject("batch_item_id", UUID.class), row.getObject("batch_id", UUID.class),
            new ObjectReference(row.getString("bucket"), row.getString("object_key"),
                row.getString("object_version"), row.getString("sha256").trim(),
                row.getLong("size_bytes"), row.getString("media_type")),
            row.getString("status"), row.getString("algorithm_outcome"),
            row.getString("employee_decision"), row.getString("usage_stage"), feedback,
            row.getTimestamp("created_at").toInstant(), row.getTimestamp("updated_at").toInstant());
    }

    private static FeedbackRecord feedback(ResultSet row) throws SQLException {
        return new FeedbackRecord(
            row.getObject("feedback_id", UUID.class), row.getObject("batch_item_id", UUID.class),
            row.getString("label"), row.getString("note"),
            row.getObject("source_review_record_id", UUID.class),
            row.getObject("supersedes_feedback_id", UUID.class), row.getInt("revision_no"),
            row.getObject("submitted_by", UUID.class), row.getTimestamp("submitted_at").toInstant());
    }

    private static Candidate candidate(ResultSet row, int number) throws SQLException {
        return new Candidate(
            row.getObject(1, UUID.class), row.getObject(2, UUID.class),
            row.getObject(3, UUID.class), row.getString(4), row.getString(5),
            row.getString(6), row.getObject(7, UUID.class), row.getObject(8, UUID.class),
            row.getTimestamp(9).toInstant());
    }

    private ExportJob exportJob(ResultSet row, int number) throws SQLException {
        String filter = row.getString("filter_snapshot");
        return new ExportJob(
            row.getObject("sample_export_job_id", UUID.class), parseFilter(filter),
            row.getInt("candidate_count"), row.getInt("exported_count"),
            row.getInt("failure_count"), row.getString("status"),
            objectReference(row, "package"), objectReference(row, "manifest"), List.of(),
            row.getTimestamp("created_at").toInstant(), timestamp(row, "expires_at"),
            List.of(), row.getString("package_bucket"), row.getString("package_object_key"), List.of());
    }

    private static ObjectReference objectReference(ResultSet row, String prefix)
            throws SQLException {
        String bucket = row.getString(prefix + "_bucket");
        String key = row.getString(prefix + "_object_key");
        String sha = row.getString(prefix + "_sha256");
        Long size = row.getObject(prefix + "_size_bytes", Long.class);
        String mediaType = row.getString(prefix + "_media_type");
        if (bucket == null || key == null || sha == null || size == null || mediaType == null) {
            return null;
        }
        return new ObjectReference(bucket, key, row.getString(prefix + "_object_version"),
            sha.trim(), size, mediaType);
    }

    private Map<String, String> parseFilter(String raw) {
        Map<String, String> result = new LinkedHashMap<>();
        try {
            JsonNode node = json.readTree(raw == null ? "{}" : raw);
            node.properties().forEach(entry -> {
                if (!entry.getValue().isTextual()) {
                    throw violation(SampleViolation.Kind.HOLD, "导出筛选快照包含非文本值");
                }
                result.put(entry.getKey(), entry.getValue().stringValue());
            });
        } catch (SampleViolation error) {
            throw error;
        } catch (RuntimeException invalid) {
            throw violation(SampleViolation.Kind.HOLD, "导出筛选快照无法解析");
        }
        return Map.copyOf(result);
    }

    private static Instant timestamp(ResultSet row, String name) throws SQLException {
        Timestamp value = row.getTimestamp(name);
        return value == null ? null : value.toInstant();
    }

    private static ExternalReceipt externalReceipt(ResultSet row, int number)
            throws SQLException {
        return new ExternalReceipt(
            row.getObject("receipt_id", UUID.class),
            row.getObject("sample_export_job_id", UUID.class),
            row.getString("receiver_name"), row.getString("external_reference"),
            row.getString("receipt_note"), row.getObject("recorded_by", UUID.class),
            row.getTimestamp("recorded_at").toInstant());
    }

    private record ExportProjection(
            UUID jobId, int candidateCount, String status, String packageBucket,
            String packageKey, int exportedCount, int failureCount, String packageSha256,
            Long packageSizeBytes, String manifestSha256, Long manifestSizeBytes,
            String failedCandidateIds) {
        boolean terminal() {
            return Set.of("SUCCEEDED", "FAILED").contains(status);
        }

        boolean matches(
                ObjectReference packageReference, ObjectReference manifestReference,
                int exported, String failedJson) {
            return exportedCount == exported
                && failureCount == countJson(failedJson)
                && Objects.equals(packageSha256, packageReference.sha256())
                && Objects.equals(packageSizeBytes, packageReference.sizeBytes())
                && Objects.equals(manifestSha256, manifestReference.sha256())
                && Objects.equals(manifestSizeBytes, manifestReference.sizeBytes())
                && Objects.equals(failedCandidateIds, failedJson);
        }

        private static int countJson(String json) {
            return json.equals("[]") ? 0 : json.split(",").length;
        }
    }

    private static SampleCursor.Boundary decodeCursor(String value) {
        try {
            return SampleCursor.decode(value);
        } catch (IllegalArgumentException invalid) {
            throw violation(SampleViolation.Kind.INTEGRITY, "游标不合法");
        }
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("运行时缺少 SHA-256", impossible);
        }
    }

    private static SampleViolation violation(SampleViolation.Kind kind, String message) {
        return new SampleViolation(kind, message);
    }

    private record Snapshot(String json, String sha256) {}

    private record ReceiptEligibility(String status, String packageSha256, Long packageSizeBytes) {}
}
