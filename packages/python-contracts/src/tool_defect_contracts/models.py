# 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
# 契约主版本: 1；源哈希: 6fc5d9465464faf374bfa54d8f20849623f912a6c3d88fdbe92ca47fba49e361
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, TypeAlias

CONTRACT_SOURCE_SHA256 = "6fc5d9465464faf374bfa54d8f20849623f912a6c3d88fdbe92ca47fba49e361"
CONTRACT_MAJOR_VERSION = 1

class AlgorithmOutcome(str, Enum):
    QUALIFIED = "QUALIFIED"
    UNQUALIFIED = "UNQUALIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"

class AttemptStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"

class BusinessDisposition(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    HOLD = "HOLD"

class CaptureStatus(str, Enum):
    CREATED = "CREATED"
    UPLOADING = "UPLOADING"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    REVIEW_PENDING = "REVIEW_PENDING"
    FINALIZED = "FINALIZED"
    FAILED = "FAILED"

class ExecutionStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    RETRY_WAIT = "RETRY_WAIT"
    DEAD = "DEAD"

class ImageKind(str, Enum):
    RAW = "RAW"
    THUMBNAIL = "THUMBNAIL"
    DEFECT_MASK = "DEFECT_MASK"
    HEATMAP = "HEATMAP"
    OVERLAY = "OVERLAY"
    POLAR = "POLAR"
    REVIEW_MASK = "REVIEW_MASK"

class LocalQueueStatus(str, Enum):
    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    SUBMITTED = "SUBMITTED"
    WAIT_RESULT = "WAIT_RESULT"
    DONE = "DONE"
    RETRY_WAIT = "RETRY_WAIT"
    LOCAL_DEAD = "LOCAL_DEAD"

class ModelStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    APPROVED = "APPROVED"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    PRODUCTION = "PRODUCTION"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"

class ObjectState(str, Enum):
    STAGING = "STAGING"
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DELETED = "DELETED"

class PreprocessQualityStatus(str, Enum):
    OK = "OK"
    WARNING = "WARNING"
    REJECTED = "REJECTED"

class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    SECOND_REVIEW_PENDING = "SECOND_REVIEW_PENDING"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"

@dataclass(frozen=True, slots=True)
class ObjectReference:
    bucket: str
    object_key: str
    sha256: str
    size_bytes: int
    media_type: str
    object_version: str | None = None

JsonObject: TypeAlias = Mapping[str, object]
