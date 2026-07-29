// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 1；源哈希: 186ea774bef9ecad130bacc65e1e35cc88ed59f479bd8ce14ecf19a84b300795
export const CONTRACT_SOURCE_SHA256 = "186ea774bef9ecad130bacc65e1e35cc88ed59f479bd8ce14ecf19a84b300795" as const;
export const CONTRACT_MAJOR_VERSION = 1 as const;

export type AlgorithmOutcome = "QUALIFIED" | "UNQUALIFIED" | "INCONCLUSIVE";
export type AttemptStatus = "RUNNING" | "SUCCEEDED" | "FAILED";
export type BusinessDisposition = "PASS" | "FAIL" | "HOLD";
export type CaptureStatus = "CREATED" | "UPLOADING" | "READY" | "SUBMITTED" | "PROCESSING" | "REVIEW_PENDING" | "FINALIZED" | "FAILED";
export type ExecutionStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "RETRY_WAIT" | "DEAD";
export type ImageKind = "RAW" | "THUMBNAIL" | "DEFECT_MASK" | "HEATMAP" | "OVERLAY" | "POLAR" | "REVIEW_MASK";
export type LocalQueueStatus = "PENDING" | "UPLOADING" | "UPLOADED" | "SUBMITTED" | "WAIT_RESULT" | "DONE" | "RETRY_WAIT" | "LOCAL_DEAD";
export type ModelStatus = "DRAFT" | "VALIDATING" | "APPROVED" | "SHADOW" | "CANARY" | "PRODUCTION" | "REJECTED" | "QUARANTINED" | "RETIRED";
export type ObjectState = "STAGING" | "AVAILABLE" | "QUARANTINED" | "DELETED";
export type PreprocessQualityStatus = "OK" | "WARNING" | "REJECTED";
export type ReviewStatus = "PENDING" | "CLAIMED" | "SECOND_REVIEW_PENDING" | "ESCALATED" | "RESOLVED" | "CANCELLED";

export interface ObjectReference {
  readonly bucket: string;
  readonly object_key: string;
  readonly sha256: string;
  readonly size_bytes: number;
  readonly media_type: string;
  readonly object_version?: string | null;
}
