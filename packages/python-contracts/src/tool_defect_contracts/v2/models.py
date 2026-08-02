# 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
# 契约主版本: 2；源哈希: 22c752871f6e08eabb41421367fff400af7513cc7fdfc2a1a5cab551308ca2f9
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

CONTRACT_SOURCE_SHA256 = "22c752871f6e08eabb41421367fff400af7513cc7fdfc2a1a5cab551308ca2f9"
CONTRACT_MAJOR_VERSION = 2

class AdminFeedbackLabel(str, Enum):
    CORRECT_DETECTION = "CORRECT_DETECTION"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    FALSE_NEGATIVE = "FALSE_NEGATIVE"
    LOCALIZATION_INACCURATE = "LOCALIZATION_INACCURATE"
    IMAGE_UNUSABLE = "IMAGE_UNUSABLE"
    UNCONFIRMED = "UNCONFIRMED"

class AlgorithmOutcome(str, Enum):
    QUALIFIED = "QUALIFIED"
    UNQUALIFIED = "UNQUALIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"

class BatchItemStatus(str, Enum):
    PENDING_UPLOAD = "PENDING_UPLOAD"
    UPLOADING = "UPLOADING"
    READY = "READY"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    QUALITY_REJECTED = "QUALITY_REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class BatchSource(str, Enum):
    MANUAL_UPLOAD = "MANUAL_UPLOAD"
    PRODUCTION_CAPTURE = "PRODUCTION_CAPTURE"

class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    UPLOADING = "UPLOADING"
    READY = "READY"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class ExportJobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"

class ImageQualityCheckStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"

class ImageQualityCheckType(str, Enum):
    DECODABLE = "DECODABLE"
    BLADE_PRESENT = "BLADE_PRESENT"
    BLADE_COMPLETE = "BLADE_COMPLETE"
    BLUR = "BLUR"
    EXPOSURE = "EXPOSURE"

class ImageQualityOverall(str, Enum):
    ACCEPTED = "ACCEPTED"
    WARNING = "WARNING"
    REJECTED = "REJECTED"

class ModelUploadStatus(str, Enum):
    AWAITING_UPLOAD = "AWAITING_UPLOAD"
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

class ModelValidationStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    HOLD = "HOLD"

class PersonRole(str, Enum):
    PRODUCTION_EMPLOYEE = "PRODUCTION_EMPLOYEE"
    ADMINISTRATOR = "ADMINISTRATOR"

class QuickReviewDecision(str, Enum):
    DEFECT_CONFIRMED = "DEFECT_CONFIRMED"
    NO_DEFECT_CONFIRMED = "NO_DEFECT_CONFIRMED"
    UNABLE_TO_DETERMINE = "UNABLE_TO_DETERMINE"

class SampleCandidateStatus(str, Enum):
    PENDING = "PENDING"
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    EXPORTED = "EXPORTED"

class UsageStage(str, Enum):
    NEW_BLADE = "NEW_BLADE"
    AFTER_ONE_WHEEL = "AFTER_ONE_WHEEL"
    AFTER_TWO_WHEELS = "AFTER_TWO_WHEELS"
    AFTER_THREE_WHEELS = "AFTER_THREE_WHEELS"
    OTHER = "OTHER"
    UNSPECIFIED = "UNSPECIFIED"

@dataclass(frozen=True, slots=True)
class ObjectReference:
    bucket: str
    object_key: str
    sha256: str
    size_bytes: int
    media_type: str
    object_version: str | None = None

@dataclass(frozen=True, slots=True)
class BatchAggregateCounts:
    total: int
    completed: int
    defect_suspected: int
    normal: int
    inconclusive: int
    quality_rejected: int
    technical_failed: int

@dataclass(frozen=True, slots=True)
class ImageQualityCheck:
    check_type: ImageQualityCheckType
    status: ImageQualityCheckStatus
    rule_id: str
    reason_code: str
    user_hint: str
    measurement: float | None = None
    threshold: float | None = None

@dataclass(frozen=True, slots=True)
class ImageQualityResult:
    overall: ImageQualityOverall
    checker_version: str
    checks: tuple[ImageQualityCheck, ...]

@dataclass(frozen=True, slots=True)
class DetectionBatch:
    batch_id: str
    batch_no: str
    source: BatchSource
    created_by: str
    usage_stage: UsageStage
    status: BatchStatus
    counts: BatchAggregateCounts
    created_at: str
    updated_at: str
    version: int
    usage_stage_note: str | None = None

@dataclass(frozen=True, slots=True)
class DetectionBatchItem:
    batch_item_id: str
    batch_id: str
    image: ObjectReference
    status: BatchItemStatus
    created_at: str
    updated_at: str
    capture_id: str | None = None
    quality: ImageQualityResult | None = None
    algorithm_outcome: AlgorithmOutcome | None = None
    quick_review_decision: QuickReviewDecision | None = None

@dataclass(frozen=True, slots=True)
class QuickReviewRecord:
    review_record_id: str
    batch_item_id: str
    decision: QuickReviewDecision
    submitted_by: str
    submitted_at: str
    idempotency_key: str
    supersedes_record_id: str | None = None
    disposition_reference: str | None = None

@dataclass(frozen=True, slots=True)
class AdminFeedbackRecord:
    feedback_id: str
    batch_item_id: str
    label: AdminFeedbackLabel
    submitted_by: str
    submitted_at: str
    note: str | None = None
    annotation_reference: ObjectReference | None = None
    source_review_record_id: str | None = None

@dataclass(frozen=True, slots=True)
class SampleCandidate:
    sample_candidate_id: str
    batch_item_id: str
    feedback_id: str
    status: SampleCandidateStatus
    created_at: str
    decision_note: str | None = None
    export_job_id: str | None = None

@dataclass(frozen=True, slots=True)
class SampleExportJob:
    sample_export_job_id: str
    filter_snapshot: Mapping[str, str]
    candidate_count: int
    status: ExportJobStatus
    created_at: str
    package: ObjectReference | None = None
    failed_candidate_ids: tuple[str, ...] = ()
    expires_at: str | None = None

@dataclass(frozen=True, slots=True)
class ModelUploadSession:
    model_upload_id: str
    quarantine_object: ObjectReference
    declared_sha256: str
    status: ModelUploadStatus
    created_at: str
    expires_at: str
    model_version: str | None = None
    description: str | None = None

@dataclass(frozen=True, slots=True)
class ModelValidationResult:
    model_upload_id: str
    status: ModelValidationStatus
    package_check: str
    security_scan: str
    load_test: str
    warmup_test: str
    fixed_sample_test: str
    evidence: ObjectReference
    external_source_note: str | None = None
    safe_error: str | None = None

@dataclass(frozen=True, slots=True)
class LegacyProvenanceSnapshot:
    source_type: str
    legacy_id: str
    immutable_summary: str
    archive_reference: str
    sha256: str
    retained_until: str

@dataclass(frozen=True, slots=True)
class StandardError:
    error_code: str
    message: str
    request_id: str
    retryable: bool
    details: Mapping[str, str] | None = None

