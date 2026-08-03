// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 2；源哈希: b30eca1ebbb6b533902ed4ba897e07c0daebd02a7ecf931154f9d2fb3ae0fc8e
export const CONTRACT_SOURCE_SHA256 = "b30eca1ebbb6b533902ed4ba897e07c0daebd02a7ecf931154f9d2fb3ae0fc8e" as const;
export const CONTRACT_MAJOR_VERSION = 2 as const;

export type AdminFeedbackLabel = "CORRECT_DETECTION" | "FALSE_POSITIVE" | "FALSE_NEGATIVE" | "LOCALIZATION_INACCURATE" | "IMAGE_UNUSABLE" | "UNCONFIRMED";
export type AlgorithmOutcome = "QUALIFIED" | "UNQUALIFIED" | "INCONCLUSIVE";
export type BatchItemStatus = "PENDING_UPLOAD" | "UPLOADING" | "READY" | "QUEUED" | "PROCESSING" | "COMPLETED" | "QUALITY_REJECTED" | "FAILED" | "CANCELLED";
export type BatchSource = "MANUAL_UPLOAD" | "PRODUCTION_CAPTURE";
export type BatchStatus = "DRAFT" | "UPLOADING" | "READY" | "PROCESSING" | "COMPLETED" | "PARTIALLY_COMPLETED" | "FAILED" | "CANCELLED";
export type ExportJobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "EXPIRED";
export type ImageQualityCheckStatus = "PASS" | "WARNING" | "FAIL" | "NOT_RUN";
export type ImageQualityCheckType = "DECODABLE" | "BLADE_PRESENT" | "BLADE_COMPLETE" | "BLUR" | "EXPOSURE";
export type ImageQualityOverall = "ACCEPTED" | "WARNING" | "REJECTED";
export type ModelUploadStatus = "AWAITING_UPLOAD" | "UPLOADED" | "VALIDATING" | "VALIDATED" | "REJECTED" | "EXPIRED";
export type ModelValidationStatus = "PASSED" | "FAILED" | "HOLD";
export type PersonRole = "PRODUCTION_EMPLOYEE" | "ADMINISTRATOR";
export type QuickReviewDecision = "DEFECT_CONFIRMED" | "NO_DEFECT_CONFIRMED" | "UNABLE_TO_DETERMINE";
export type SampleCandidateStatus = "PENDING" | "INCLUDED" | "EXCLUDED" | "EXPORTED";
export type UsageStage = "NEW_BLADE" | "AFTER_ONE_WHEEL" | "AFTER_TWO_WHEELS" | "AFTER_THREE_WHEELS" | "OTHER" | "UNSPECIFIED";

export type ObjectReference = Readonly<{ bucket: string; object_key: string; sha256: string; size_bytes: number; media_type: string; object_version?: string }>;
export type BatchAggregateCounts = Readonly<{ total: number; completed: number; defect_suspected: number; normal: number; inconclusive: number; quality_rejected: number; technical_failed: number }>;
export type ImageQualityCheck = Readonly<{ check_type: ImageQualityCheckType; status: ImageQualityCheckStatus; rule_id: string; reason_code: string; user_hint: string; measurement?: number; threshold?: number }>;
export type ImageQualityResult = Readonly<{ overall: ImageQualityOverall; checker_version: string; checks: ReadonlyArray<ImageQualityCheck> }>;
export type DetectionBatch = Readonly<{ batch_id: string; batch_no: string; source: BatchSource; created_by: string; usage_stage: UsageStage; usage_stage_note?: string; status: BatchStatus; counts: BatchAggregateCounts; created_at: string; updated_at: string; version: number }>;
export type DetectionBatchItem = Readonly<{ batch_item_id: string; batch_id: string; capture_id?: string; image: ObjectReference; status: BatchItemStatus; quality?: ImageQualityResult; algorithm_outcome?: AlgorithmOutcome; quick_review_decision?: QuickReviewDecision; created_at: string; updated_at: string }>;
export type QuickReviewRecord = Readonly<{ review_record_id: string; batch_item_id: string; decision: QuickReviewDecision; submitted_by: string; submitted_at: string; idempotency_key: string; supersedes_record_id?: string; disposition_reference?: string }>;
export type AdminFeedbackRecord = Readonly<{ feedback_id: string; batch_item_id: string; label: AdminFeedbackLabel; note?: string; annotation_reference?: ObjectReference; source_review_record_id?: string; submitted_by: string; submitted_at: string }>;
export type SampleCandidate = Readonly<{ sample_candidate_id: string; batch_item_id: string; feedback_id: string; status: SampleCandidateStatus; decision_note?: string; export_job_id?: string; created_at: string }>;
export type SampleExportJob = Readonly<{ sample_export_job_id: string; filter_snapshot: Readonly<Record<string, string>>; candidate_count: number; status: ExportJobStatus; package?: ObjectReference; failed_candidate_ids?: ReadonlyArray<string>; created_at: string; expires_at?: string }>;
export type ModelUploadSession = Readonly<{ model_upload_id: string; quarantine_object: ObjectReference; declared_sha256: string; model_version?: string; description?: string; status: ModelUploadStatus; created_at: string; expires_at: string }>;
export type ModelValidationResult = Readonly<{ model_upload_id: string; status: ModelValidationStatus; package_check: string; security_scan: string; load_test: string; warmup_test: string; fixed_sample_test: string; evidence: ObjectReference; external_source_note?: string; safe_error?: string }>;
export type LegacyProvenanceSnapshot = Readonly<{ source_type: "LEGACY_DATASET" | "LEGACY_TRAINING"; legacy_id: string; immutable_summary: string; archive_reference: string; sha256: string; retained_until: string }>;
export type StandardError = Readonly<{ error_code: string; message: string; request_id: string; retryable: boolean; details?: Readonly<Record<string, string>> }>;
