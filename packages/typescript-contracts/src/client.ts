// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 1；源哈希: f72a5a3390cfe2d9530d4d12b3bb2d572a57fbbb290c10bf886c1479509935fb
import type {
  Acknowledgement,
  ActionRequest,
  AlgorithmOutcome,
  AnnotationUploadTicketRequest,
  ApprovalRequest,
  AsyncAccepted,
  AttemptStartRequest,
  AttemptStartResponse,
  AttemptStatus,
  AuditRecordPage,
  AuditRecordSummary,
  BusinessDisposition,
  CaptureCreateRequest,
  CaptureCreateResponse,
  CaptureStatus,
  CaptureStatusResponse,
  CaptureSyncQueryRequest,
  CaptureSyncQueryResponse,
  ClientImage,
  Common,
  CommonAdminFeedbackLabel,
  CommonAdminFeedbackRecord,
  CommonAlgorithmOutcome,
  CommonBatchAggregateCounts,
  CommonBatchItemStatus,
  CommonBatchSource,
  CommonBatchStatus,
  CommonDetectionBatch,
  CommonDetectionBatchItem,
  CommonExportJobStatus,
  CommonImageQualityCheck,
  CommonImageQualityCheckStatus,
  CommonImageQualityCheckType,
  CommonImageQualityOverall,
  CommonImageQualityResult,
  CommonLegacyProvenanceSnapshot,
  CommonModelUploadSession,
  CommonModelUploadStatus,
  CommonModelValidationResult,
  CommonModelValidationStatus,
  CommonObjectReference,
  CommonPersonRole,
  CommonQuickReviewDecision,
  CommonQuickReviewRecord,
  CommonSampleCandidate,
  CommonSampleCandidateStatus,
  CommonSampleDownloadTicket,
  CommonSampleExportJob,
  CommonSampleExportTarget,
  CommonSampleExternalReceipt,
  CommonSha256,
  CommonStandardError,
  CommonUsageStage,
  CommonUtcTimestamp,
  CommonUuid,
  CsrfTokenResponse,
  DatasetApprovalRequest,
  DatasetCandidateManifestApprovalResponse,
  DatasetCandidateManifestPage,
  DatasetCandidateManifestSummary,
  DatasetCreateRequest,
  DatasetPage,
  DatasetSummary,
  DatasetVersionApprovalResponse,
  DatasetVersionCreateRequest,
  DatasetVersionDiff,
  DatasetVersionDiffItem,
  DatasetVersionPage,
  DatasetVersionSummary,
  DetectionDetail,
  DetectionFailureRequest,
  DetectionPage,
  DetectionResult,
  DetectionResultDefectRegion,
  DetectionResultDerivedArtifact,
  DetectionSummary,
  ErrorDetail,
  ExecutionStatus,
  HeartbeatRequest,
  ImageAccessTicketRequest,
  ImageAccessTicketResponse,
  ImageKind,
  ImageReference,
  LocalLoginRequest,
  LocalQueueStatus,
  LocalUserCreateRequest,
  LocalUserDisplayNameRequest,
  LocalUserList,
  LocalUserPasswordResetRequest,
  LocalUserRoleMigrationDecision,
  LocalUserRoleMigrationList,
  LocalUserRoleMigrationPreview,
  LocalUserRoleMigrationRequest,
  LocalUserRolesRequest,
  LocalUserSession,
  LocalUserStatusRequest,
  LocalUserSummary,
  ModelCreateRequest,
  ModelDeploymentCreateRequest,
  ModelDeploymentPage,
  ModelDeploymentResponse,
  ModelDeploymentSummary,
  ModelPage,
  ModelStatus,
  ModelSummary,
  ModelVersionPage,
  ModelVersionRegisterRequest,
  ModelVersionRegistrationResponse,
  ModelVersionResponse,
  ModelVersionSummary,
  ObjectCompleteRequest,
  ObjectCompleteResponse,
  ObjectReference,
  ObjectState,
  OverviewCaptureCounts,
  OverviewFleetHealth,
  OverviewInferenceHealth,
  OverviewModelRuntime,
  OverviewOutcomeComparison,
  OverviewOutcomeCounts,
  OverviewProductionModel,
  OverviewQualityComparison,
  OverviewQualityCounts,
  OverviewReviewBacklog,
  OverviewWindow,
  PasswordChangeRequest,
  PreprocessQualityStatus,
  QualityMetricReason,
  QualityMetrics,
  QualitySummary,
  ReadinessResponse,
  ReasonRequest,
  ResultAcceptedResponse,
  ReviewStatus,
  ReviewSubmissionRequest,
  ReviewSubmissionResponse,
  ReviewSummary,
  ReviewTask,
  ReviewTaskPage,
  ReviewWorkspace,
  RollbackRequest,
  RuntimeModelsResponse,
  Sha256,
  StandardError,
  SubmitCaptureRequest,
  SubmitCaptureResponse,
  SystemOverview,
  Traceparent,
  TrainingRunCreateRequest,
  TrainingRunPage,
  TrainingRunStatusUpdateRequest,
  TrainingRunSummary,
  Trigger,
  UploadTicketRenewRequest,
  UploadTicketResponse,
  UtcTimestamp,
  Uuid,
  ValidationDecisionRequest,
  Version,
  VersionedResource,
} from "./index.js";
import type { JsonObject as SchemaJsonObject } from "./index.js";

export type JsonObject = SchemaJsonObject;
export type ApiResponseMediaCategory =
  | "json"
  | "event-stream"
  | "binary"
  | "text"
  | "empty"
  | "other"
  | "mixed";

export const API_OPERATION_METADATA = {
  approveDatasetCandidateManifest: {
    method: "POST",
    path: "/api/v1/dataset-candidate-manifests/{candidate_manifest_id}/approval",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  approveDatasetVersion: {
    method: "POST",
    path: "/api/v1/dataset-versions/{dataset_version_id}/approval",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  approveModelDeployment: {
    method: "POST",
    path: "/api/v1/model-deployments/{model_deployment_id}/approvals",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  changeLocalPassword: {
    method: "POST",
    path: "/api/v1/auth/password/change",
    responseMediaCategory: "empty",
    responseMediaTypes: [],
  },
  claimReviewTask: {
    method: "POST",
    path: "/api/v1/review-tasks/{review_task_id}/claim",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  completeCaptureImage: {
    method: "POST",
    path: "/api/v1/edge/captures/{capture_id}/images/{image_id}/complete",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  completeReviewAnnotation: {
    method: "POST",
    path: "/api/v1/review-tasks/{review_task_id}/annotations/{image_id}/complete",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  confirmLocalUserRoleMigration: {
    method: "POST",
    path: "/api/v1/users/{user_id}/role-migration",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  createAnnotationUploadTicket: {
    method: "POST",
    path: "/api/v1/review-tasks/{review_task_id}/annotation-upload-ticket",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  createCapture: {
    method: "POST",
    path: "/api/v1/edge/captures",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  createDataset: {
    method: "POST",
    path: "/api/v1/datasets",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  createDatasetVersion: {
    method: "POST",
    path: "/api/v1/dataset-versions",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  createImageAccessTicket: {
    method: "POST",
    path: "/api/v1/images/{image_id}/access-ticket",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  createLocalUser: {
    method: "POST",
    path: "/api/v1/users",
    responseMediaCategory: "empty",
    responseMediaTypes: [],
  },
  createModel: {
    method: "POST",
    path: "/api/v1/models",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  createModelDeployment: {
    method: "POST",
    path: "/api/v1/model-deployments",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  createTrainingRun: {
    method: "POST",
    path: "/api/v1/training-runs",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  diffDatasetVersions: {
    method: "GET",
    path: "/api/v1/dataset-versions/diff",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getCsrfToken: {
    method: "GET",
    path: "/api/v1/auth/csrf",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getDatasetVersion: {
    method: "GET",
    path: "/api/v1/dataset-versions/{dataset_version_id}",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getDetection: {
    method: "GET",
    path: "/api/v1/detections/{detection_task_id}",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getEdgeCapture: {
    method: "GET",
    path: "/api/v1/edge/captures/{capture_id}",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getInferenceReadiness: {
    method: "GET",
    path: "/internal/v1/runtime/ready",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getLocalUserSession: {
    method: "GET",
    path: "/api/v1/auth/session",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getModelDeployment: {
    method: "GET",
    path: "/api/v1/model-deployments/{model_deployment_id}",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getModelVersion: {
    method: "GET",
    path: "/api/v1/model-versions/{model_version_id}",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getQualityMetrics: {
    method: "GET",
    path: "/api/v1/quality/metrics",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getReviewWorkspace: {
    method: "GET",
    path: "/api/v1/review-tasks/{review_task_id}",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getSystemOverview: {
    method: "GET",
    path: "/api/v1/dashboard/overview",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getTrainingRun: {
    method: "GET",
    path: "/api/v1/training-runs/{training_run_id}",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listAuditRecords: {
    method: "GET",
    path: "/api/v1/audit-records",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listDatasetCandidateManifests: {
    method: "GET",
    path: "/api/v1/dataset-candidate-manifests",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listDatasetVersionCatalog: {
    method: "GET",
    path: "/api/v1/dataset-versions",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listDatasetVersions: {
    method: "GET",
    path: "/api/v1/datasets/{dataset_id}/versions",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listDatasets: {
    method: "GET",
    path: "/api/v1/datasets",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listDetections: {
    method: "GET",
    path: "/api/v1/detections",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listLocalUsers: {
    method: "GET",
    path: "/api/v1/users",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listModelDeployments: {
    method: "GET",
    path: "/api/v1/model-deployments",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listModelVersions: {
    method: "GET",
    path: "/api/v1/model-versions",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listModels: {
    method: "GET",
    path: "/api/v1/models",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listReviewTasks: {
    method: "GET",
    path: "/api/v1/review-tasks",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listRuntimeModels: {
    method: "GET",
    path: "/internal/v1/runtime/models",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listTrainingRuns: {
    method: "GET",
    path: "/api/v1/training-runs",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  loginLocalUser: {
    method: "POST",
    path: "/api/v1/auth/login",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  logoutLocalUser: {
    method: "POST",
    path: "/api/v1/auth/logout",
    responseMediaCategory: "empty",
    responseMediaTypes: [],
  },
  previewLocalUserRoleMigrations: {
    method: "GET",
    path: "/api/v1/users/role-migration-preview",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  queryCaptureSync: {
    method: "POST",
    path: "/api/v1/edge/sync/captures/query",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  registerModelVersion: {
    method: "POST",
    path: "/api/v1/model-versions",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  releaseReviewTask: {
    method: "POST",
    path: "/api/v1/review-tasks/{review_task_id}/release",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  renewCaptureImageUploadTicket: {
    method: "POST",
    path: "/api/v1/edge/captures/{capture_id}/images/{image_id}/upload-ticket",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  reportDeviceHeartbeat: {
    method: "POST",
    path: "/api/v1/edge/devices/{device_id}/heartbeat",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  resetLocalUserPassword: {
    method: "POST",
    path: "/api/v1/users/{user_id}/password-reset",
    responseMediaCategory: "empty",
    responseMediaTypes: [],
  },
  retryDetection: {
    method: "POST",
    path: "/api/v1/detections/{detection_task_id}/retry",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  rollbackModelDeployment: {
    method: "POST",
    path: "/api/v1/model-deployments/{model_deployment_id}/rollback",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  startDetectionAttempt: {
    method: "POST",
    path: "/internal/v1/detection-tasks/{detection_task_id}/attempts",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  streamAuthorizedEvents: {
    method: "GET",
    path: "/api/v1/events/stream",
    responseMediaCategory: "event-stream",
    responseMediaTypes: ["text/event-stream"],
  },
  submitCapture: {
    method: "POST",
    path: "/api/v1/edge/captures/{capture_id}/submit",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  submitDetectionFailure: {
    method: "PUT",
    path: "/internal/v1/detection-attempts/{attempt_id}/failure",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  submitDetectionResult: {
    method: "PUT",
    path: "/internal/v1/detection-attempts/{attempt_id}/result",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  submitModelValidationDecision: {
    method: "POST",
    path: "/api/v1/model-versions/{model_version_id}/validation-decisions",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  submitReview: {
    method: "POST",
    path: "/api/v1/review-tasks/{review_task_id}/submissions",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  updateLocalUserDisplayName: {
    method: "PATCH",
    path: "/api/v1/users/{user_id}/display-name",
    responseMediaCategory: "empty",
    responseMediaTypes: [],
  },
  updateLocalUserRoles: {
    method: "PUT",
    path: "/api/v1/users/{user_id}/roles",
    responseMediaCategory: "empty",
    responseMediaTypes: [],
  },
  updateLocalUserStatus: {
    method: "PATCH",
    path: "/api/v1/users/{user_id}/status",
    responseMediaCategory: "empty",
    responseMediaTypes: [],
  },
  updateTrainingRunStatus: {
    method: "PUT",
    path: "/internal/v1/training-runs/{training_run_id}/status",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
} as const satisfies Readonly<Record<string, {
  readonly method: string;
  readonly path: string;
  readonly responseMediaCategory: ApiResponseMediaCategory;
  readonly responseMediaTypes: readonly string[];
}>>;

export type ApiOperationId = keyof typeof API_OPERATION_METADATA;

export type ApproveDatasetCandidateManifestRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "candidate_manifest_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (DatasetApprovalRequest);
}>;

export type ApproveDatasetVersionRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "dataset_version_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (DatasetApprovalRequest);
}>;

export type ApproveModelDeploymentRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "model_deployment_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; readonly "If-Match": string; }>;
  readonly body: (ApprovalRequest);
}>;

export type ChangeLocalPasswordRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (PasswordChangeRequest);
}>;

export type ClaimReviewTaskRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "review_task_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; readonly "If-Match": string; }>;
  readonly body: (ActionRequest);
}>;

export type CompleteCaptureImageRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "capture_id": Uuid; readonly "image_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (ObjectCompleteRequest);
}>;

export type CompleteReviewAnnotationRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "image_id": Uuid; readonly "review_task_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (ObjectCompleteRequest);
}>;

export type ConfirmLocalUserRoleMigrationRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "user_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (LocalUserRoleMigrationRequest);
}>;

export type CreateAnnotationUploadTicketRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "review_task_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (AnnotationUploadTicketRequest);
}>;

export type CreateCaptureRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; readonly "X-Request-Id"?: Uuid; readonly "traceparent"?: Traceparent; }>;
  readonly body: (CaptureCreateRequest);
}>;

export type CreateDatasetRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (DatasetCreateRequest);
}>;

export type CreateDatasetVersionRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (DatasetVersionCreateRequest);
}>;

export type CreateImageAccessTicketRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "image_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (ImageAccessTicketRequest);
}>;

export type CreateLocalUserRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (LocalUserCreateRequest);
}>;

export type CreateModelRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (ModelCreateRequest);
}>;

export type CreateModelDeploymentRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (ModelDeploymentCreateRequest);
}>;

export type CreateTrainingRunRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (TrainingRunCreateRequest);
}>;

export type DiffDatasetVersionsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query: Readonly<{ readonly "from": Uuid; readonly "to": Uuid; }>;
  readonly headers?: never;
  readonly body?: never;
}>;

export type GetCsrfTokenRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type GetDatasetVersionRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "dataset_version_id": Uuid; }>;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type GetDetectionRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "detection_task_id": Uuid; }>;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type GetEdgeCaptureRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "capture_id": Uuid; }>;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type GetInferenceReadinessRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type GetLocalUserSessionRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type GetModelDeploymentRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "model_deployment_id": Uuid; }>;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type GetModelVersionRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "model_version_id": Uuid; }>;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type GetQualityMetricsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: Readonly<{ readonly "end_date"?: string; readonly "model_version_id"?: Uuid; readonly "start_date"?: string; }>;
  readonly headers?: never;
  readonly body?: never;
}>;

export type GetReviewWorkspaceRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "review_task_id": Uuid; }>;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type GetSystemOverviewRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type GetTrainingRunRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "training_run_id": Uuid; }>;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type ListAuditRecordsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: Readonly<{ readonly "action"?: string; readonly "actor_id"?: string; readonly "cursor"?: string; readonly "end_time"?: UtcTimestamp; readonly "page_size"?: number; readonly "resource_id"?: string; readonly "resource_type"?: string; readonly "result"?: string; readonly "start_time"?: UtcTimestamp; }>;
  readonly headers?: Readonly<{ readonly "X-Request-Id"?: Uuid; readonly "traceparent"?: Traceparent; }>;
  readonly body?: never;
}>;

export type ListDatasetCandidateManifestsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query: Readonly<{ readonly "approval_state"?: "REGISTERED" | "APPROVED" | "REJECTED"; readonly "cursor"?: string; readonly "dataset_id": Uuid; readonly "page_size"?: number; }>;
  readonly headers?: never;
  readonly body?: never;
}>;

export type ListDatasetVersionCatalogRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: Readonly<{ readonly "cursor"?: string; readonly "dataset_id"?: Uuid; readonly "page_size"?: number; readonly "status"?: "BUILDING" | "VALIDATING" | "FROZEN" | "REJECTED"; }>;
  readonly headers?: never;
  readonly body?: never;
}>;

export type ListDatasetVersionsRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "dataset_id": Uuid; }>;
  readonly query?: Readonly<{ readonly "cursor"?: string; readonly "page_size"?: number; }>;
  readonly headers?: never;
  readonly body?: never;
}>;

export type ListDatasetsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: Readonly<{ readonly "cursor"?: string; readonly "page_size"?: number; }>;
  readonly headers?: never;
  readonly body?: never;
}>;

export type ListDetectionsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: Readonly<{ readonly "algorithm_outcome"?: AlgorithmOutcome; readonly "business_disposition"?: BusinessDisposition; readonly "cursor"?: string; readonly "model_version"?: string; readonly "page_size"?: number; }>;
  readonly headers?: never;
  readonly body?: never;
}>;

export type ListLocalUsersRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type ListModelDeploymentsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: Readonly<{ readonly "cursor"?: string; readonly "model_version_id"?: Uuid; readonly "page_size"?: number; readonly "status"?: "REQUESTED" | "APPROVED" | "ACTIVE" | "ROLLED_BACK" | "REJECTED"; }>;
  readonly headers?: never;
  readonly body?: never;
}>;

export type ListModelVersionsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: Readonly<{ readonly "approval_state"?: "CANDIDATE" | "VALIDATED" | "APPROVED" | "REJECTED" | "RETIRED"; readonly "cursor"?: string | null; readonly "model_id"?: Uuid; readonly "page_size"?: number; }>;
  readonly headers?: never;
  readonly body?: never;
}>;

export type ListModelsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: Readonly<{ readonly "cursor"?: string; readonly "page_size"?: number; }>;
  readonly headers?: never;
  readonly body?: never;
}>;

export type ListReviewTasksRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: Readonly<{ readonly "cursor"?: string; readonly "page_size"?: number; readonly "status"?: ReviewStatus; }>;
  readonly headers?: never;
  readonly body?: never;
}>;

export type ListRuntimeModelsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type ListTrainingRunsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: Readonly<{ readonly "cursor"?: string; readonly "page_size"?: number; readonly "status"?: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED"; }>;
  readonly headers?: never;
  readonly body?: never;
}>;

export type LoginLocalUserRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (LocalLoginRequest);
}>;

export type LogoutLocalUserRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body?: never;
}>;

export type PreviewLocalUserRoleMigrationsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers?: never;
  readonly body?: never;
}>;

export type QueryCaptureSyncRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (CaptureSyncQueryRequest);
}>;

export type RegisterModelVersionRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (ModelVersionRegisterRequest);
}>;

export type ReleaseReviewTaskRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "review_task_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; readonly "If-Match": string; }>;
  readonly body: (ActionRequest);
}>;

export type RenewCaptureImageUploadTicketRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "capture_id": Uuid; readonly "image_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (UploadTicketRenewRequest);
}>;

export type ReportDeviceHeartbeatRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "device_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (HeartbeatRequest);
}>;

export type ResetLocalUserPasswordRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "user_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (LocalUserPasswordResetRequest);
}>;

export type RetryDetectionRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "detection_task_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (ReasonRequest);
}>;

export type RollbackModelDeploymentRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "model_deployment_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; readonly "If-Match": string; }>;
  readonly body: (RollbackRequest);
}>;

export type StartDetectionAttemptRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "detection_task_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; readonly "traceparent"?: Traceparent; }>;
  readonly body: (AttemptStartRequest);
}>;

export type StreamAuthorizedEventsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers?: Readonly<{ readonly "Last-Event-ID"?: string; }>;
  readonly body?: never;
}>;

export type SubmitCaptureRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "capture_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (SubmitCaptureRequest);
}>;

export type SubmitDetectionFailureRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "attempt_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; readonly "traceparent"?: Traceparent; }>;
  readonly body: (DetectionFailureRequest);
}>;

export type SubmitDetectionResultRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "attempt_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; readonly "traceparent"?: Traceparent; }>;
  readonly body: (DetectionResult);
}>;

export type SubmitModelValidationDecisionRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "model_version_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (ValidationDecisionRequest);
}>;

export type SubmitReviewRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "review_task_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; readonly "If-Match": string; }>;
  readonly body: (ReviewSubmissionRequest);
}>;

export type UpdateLocalUserDisplayNameRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "user_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (LocalUserDisplayNameRequest);
}>;

export type UpdateLocalUserRolesRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "user_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (LocalUserRolesRequest);
}>;

export type UpdateLocalUserStatusRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "user_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (LocalUserStatusRequest);
}>;

export type UpdateTrainingRunStatusRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "training_run_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (TrainingRunStatusUpdateRequest);
}>;

export type ApiOperationRequestMap = Readonly<{
  readonly approveDatasetCandidateManifest: ApproveDatasetCandidateManifestRequestEnvelope;
  readonly approveDatasetVersion: ApproveDatasetVersionRequestEnvelope;
  readonly approveModelDeployment: ApproveModelDeploymentRequestEnvelope;
  readonly changeLocalPassword: ChangeLocalPasswordRequestEnvelope;
  readonly claimReviewTask: ClaimReviewTaskRequestEnvelope;
  readonly completeCaptureImage: CompleteCaptureImageRequestEnvelope;
  readonly completeReviewAnnotation: CompleteReviewAnnotationRequestEnvelope;
  readonly confirmLocalUserRoleMigration: ConfirmLocalUserRoleMigrationRequestEnvelope;
  readonly createAnnotationUploadTicket: CreateAnnotationUploadTicketRequestEnvelope;
  readonly createCapture: CreateCaptureRequestEnvelope;
  readonly createDataset: CreateDatasetRequestEnvelope;
  readonly createDatasetVersion: CreateDatasetVersionRequestEnvelope;
  readonly createImageAccessTicket: CreateImageAccessTicketRequestEnvelope;
  readonly createLocalUser: CreateLocalUserRequestEnvelope;
  readonly createModel: CreateModelRequestEnvelope;
  readonly createModelDeployment: CreateModelDeploymentRequestEnvelope;
  readonly createTrainingRun: CreateTrainingRunRequestEnvelope;
  readonly diffDatasetVersions: DiffDatasetVersionsRequestEnvelope;
  readonly getCsrfToken: GetCsrfTokenRequestEnvelope;
  readonly getDatasetVersion: GetDatasetVersionRequestEnvelope;
  readonly getDetection: GetDetectionRequestEnvelope;
  readonly getEdgeCapture: GetEdgeCaptureRequestEnvelope;
  readonly getInferenceReadiness: GetInferenceReadinessRequestEnvelope;
  readonly getLocalUserSession: GetLocalUserSessionRequestEnvelope;
  readonly getModelDeployment: GetModelDeploymentRequestEnvelope;
  readonly getModelVersion: GetModelVersionRequestEnvelope;
  readonly getQualityMetrics: GetQualityMetricsRequestEnvelope;
  readonly getReviewWorkspace: GetReviewWorkspaceRequestEnvelope;
  readonly getSystemOverview: GetSystemOverviewRequestEnvelope;
  readonly getTrainingRun: GetTrainingRunRequestEnvelope;
  readonly listAuditRecords: ListAuditRecordsRequestEnvelope;
  readonly listDatasetCandidateManifests: ListDatasetCandidateManifestsRequestEnvelope;
  readonly listDatasetVersionCatalog: ListDatasetVersionCatalogRequestEnvelope;
  readonly listDatasetVersions: ListDatasetVersionsRequestEnvelope;
  readonly listDatasets: ListDatasetsRequestEnvelope;
  readonly listDetections: ListDetectionsRequestEnvelope;
  readonly listLocalUsers: ListLocalUsersRequestEnvelope;
  readonly listModelDeployments: ListModelDeploymentsRequestEnvelope;
  readonly listModelVersions: ListModelVersionsRequestEnvelope;
  readonly listModels: ListModelsRequestEnvelope;
  readonly listReviewTasks: ListReviewTasksRequestEnvelope;
  readonly listRuntimeModels: ListRuntimeModelsRequestEnvelope;
  readonly listTrainingRuns: ListTrainingRunsRequestEnvelope;
  readonly loginLocalUser: LoginLocalUserRequestEnvelope;
  readonly logoutLocalUser: LogoutLocalUserRequestEnvelope;
  readonly previewLocalUserRoleMigrations: PreviewLocalUserRoleMigrationsRequestEnvelope;
  readonly queryCaptureSync: QueryCaptureSyncRequestEnvelope;
  readonly registerModelVersion: RegisterModelVersionRequestEnvelope;
  readonly releaseReviewTask: ReleaseReviewTaskRequestEnvelope;
  readonly renewCaptureImageUploadTicket: RenewCaptureImageUploadTicketRequestEnvelope;
  readonly reportDeviceHeartbeat: ReportDeviceHeartbeatRequestEnvelope;
  readonly resetLocalUserPassword: ResetLocalUserPasswordRequestEnvelope;
  readonly retryDetection: RetryDetectionRequestEnvelope;
  readonly rollbackModelDeployment: RollbackModelDeploymentRequestEnvelope;
  readonly startDetectionAttempt: StartDetectionAttemptRequestEnvelope;
  readonly streamAuthorizedEvents: StreamAuthorizedEventsRequestEnvelope;
  readonly submitCapture: SubmitCaptureRequestEnvelope;
  readonly submitDetectionFailure: SubmitDetectionFailureRequestEnvelope;
  readonly submitDetectionResult: SubmitDetectionResultRequestEnvelope;
  readonly submitModelValidationDecision: SubmitModelValidationDecisionRequestEnvelope;
  readonly submitReview: SubmitReviewRequestEnvelope;
  readonly updateLocalUserDisplayName: UpdateLocalUserDisplayNameRequestEnvelope;
  readonly updateLocalUserRoles: UpdateLocalUserRolesRequestEnvelope;
  readonly updateLocalUserStatus: UpdateLocalUserStatusRequestEnvelope;
  readonly updateTrainingRunStatus: UpdateTrainingRunStatusRequestEnvelope;
}>;

export interface ApiClient {
  approveDatasetCandidateManifest(request: ApproveDatasetCandidateManifestRequestEnvelope): Promise<JsonObject>;
  approveDatasetVersion(request: ApproveDatasetVersionRequestEnvelope): Promise<JsonObject>;
  approveModelDeployment(request: ApproveModelDeploymentRequestEnvelope): Promise<JsonObject>;
  changeLocalPassword(request: ChangeLocalPasswordRequestEnvelope): Promise<JsonObject>;
  claimReviewTask(request: ClaimReviewTaskRequestEnvelope): Promise<JsonObject>;
  completeCaptureImage(request: CompleteCaptureImageRequestEnvelope): Promise<JsonObject>;
  completeReviewAnnotation(request: CompleteReviewAnnotationRequestEnvelope): Promise<JsonObject>;
  confirmLocalUserRoleMigration(request: ConfirmLocalUserRoleMigrationRequestEnvelope): Promise<JsonObject>;
  createAnnotationUploadTicket(request: CreateAnnotationUploadTicketRequestEnvelope): Promise<JsonObject>;
  createCapture(request: CreateCaptureRequestEnvelope): Promise<JsonObject>;
  createDataset(request: CreateDatasetRequestEnvelope): Promise<JsonObject>;
  createDatasetVersion(request: CreateDatasetVersionRequestEnvelope): Promise<JsonObject>;
  createImageAccessTicket(request: CreateImageAccessTicketRequestEnvelope): Promise<JsonObject>;
  createLocalUser(request: CreateLocalUserRequestEnvelope): Promise<JsonObject>;
  createModel(request: CreateModelRequestEnvelope): Promise<JsonObject>;
  createModelDeployment(request: CreateModelDeploymentRequestEnvelope): Promise<JsonObject>;
  createTrainingRun(request: CreateTrainingRunRequestEnvelope): Promise<JsonObject>;
  diffDatasetVersions(request: DiffDatasetVersionsRequestEnvelope): Promise<JsonObject>;
  getCsrfToken(request?: GetCsrfTokenRequestEnvelope): Promise<JsonObject>;
  getDatasetVersion(request: GetDatasetVersionRequestEnvelope): Promise<JsonObject>;
  getDetection(request: GetDetectionRequestEnvelope): Promise<JsonObject>;
  getEdgeCapture(request: GetEdgeCaptureRequestEnvelope): Promise<JsonObject>;
  getInferenceReadiness(request?: GetInferenceReadinessRequestEnvelope): Promise<JsonObject>;
  getLocalUserSession(request?: GetLocalUserSessionRequestEnvelope): Promise<JsonObject>;
  getModelDeployment(request: GetModelDeploymentRequestEnvelope): Promise<JsonObject>;
  getModelVersion(request: GetModelVersionRequestEnvelope): Promise<JsonObject>;
  getQualityMetrics(request?: GetQualityMetricsRequestEnvelope): Promise<JsonObject>;
  getReviewWorkspace(request: GetReviewWorkspaceRequestEnvelope): Promise<JsonObject>;
  getSystemOverview(request?: GetSystemOverviewRequestEnvelope): Promise<JsonObject>;
  getTrainingRun(request: GetTrainingRunRequestEnvelope): Promise<JsonObject>;
  listAuditRecords(request?: ListAuditRecordsRequestEnvelope): Promise<JsonObject>;
  listDatasetCandidateManifests(request: ListDatasetCandidateManifestsRequestEnvelope): Promise<JsonObject>;
  listDatasetVersionCatalog(request?: ListDatasetVersionCatalogRequestEnvelope): Promise<JsonObject>;
  listDatasetVersions(request: ListDatasetVersionsRequestEnvelope): Promise<JsonObject>;
  listDatasets(request?: ListDatasetsRequestEnvelope): Promise<JsonObject>;
  listDetections(request?: ListDetectionsRequestEnvelope): Promise<JsonObject>;
  listLocalUsers(request?: ListLocalUsersRequestEnvelope): Promise<JsonObject>;
  listModelDeployments(request?: ListModelDeploymentsRequestEnvelope): Promise<JsonObject>;
  listModelVersions(request?: ListModelVersionsRequestEnvelope): Promise<JsonObject>;
  listModels(request?: ListModelsRequestEnvelope): Promise<JsonObject>;
  listReviewTasks(request?: ListReviewTasksRequestEnvelope): Promise<JsonObject>;
  listRuntimeModels(request?: ListRuntimeModelsRequestEnvelope): Promise<JsonObject>;
  listTrainingRuns(request?: ListTrainingRunsRequestEnvelope): Promise<JsonObject>;
  loginLocalUser(request: LoginLocalUserRequestEnvelope): Promise<JsonObject>;
  logoutLocalUser(request: LogoutLocalUserRequestEnvelope): Promise<JsonObject>;
  previewLocalUserRoleMigrations(request?: PreviewLocalUserRoleMigrationsRequestEnvelope): Promise<JsonObject>;
  queryCaptureSync(request: QueryCaptureSyncRequestEnvelope): Promise<JsonObject>;
  registerModelVersion(request: RegisterModelVersionRequestEnvelope): Promise<JsonObject>;
  releaseReviewTask(request: ReleaseReviewTaskRequestEnvelope): Promise<JsonObject>;
  renewCaptureImageUploadTicket(request: RenewCaptureImageUploadTicketRequestEnvelope): Promise<JsonObject>;
  reportDeviceHeartbeat(request: ReportDeviceHeartbeatRequestEnvelope): Promise<JsonObject>;
  resetLocalUserPassword(request: ResetLocalUserPasswordRequestEnvelope): Promise<JsonObject>;
  retryDetection(request: RetryDetectionRequestEnvelope): Promise<JsonObject>;
  rollbackModelDeployment(request: RollbackModelDeploymentRequestEnvelope): Promise<JsonObject>;
  startDetectionAttempt(request: StartDetectionAttemptRequestEnvelope): Promise<JsonObject>;
  streamAuthorizedEvents(request?: StreamAuthorizedEventsRequestEnvelope): Promise<JsonObject>;
  submitCapture(request: SubmitCaptureRequestEnvelope): Promise<JsonObject>;
  submitDetectionFailure(request: SubmitDetectionFailureRequestEnvelope): Promise<JsonObject>;
  submitDetectionResult(request: SubmitDetectionResultRequestEnvelope): Promise<JsonObject>;
  submitModelValidationDecision(request: SubmitModelValidationDecisionRequestEnvelope): Promise<JsonObject>;
  submitReview(request: SubmitReviewRequestEnvelope): Promise<JsonObject>;
  updateLocalUserDisplayName(request: UpdateLocalUserDisplayNameRequestEnvelope): Promise<JsonObject>;
  updateLocalUserRoles(request: UpdateLocalUserRolesRequestEnvelope): Promise<JsonObject>;
  updateLocalUserStatus(request: UpdateLocalUserStatusRequestEnvelope): Promise<JsonObject>;
  updateTrainingRunStatus(request: UpdateTrainingRunStatusRequestEnvelope): Promise<JsonObject>;
}
