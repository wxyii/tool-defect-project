// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 1；源哈希: 3578f82330fbba2e9e500f67fd1b574296707f5b20058cae9d70ed9bc3868ce5
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
  BusinessDisposition,
  CaptureCreateRequest,
  CaptureCreateResponse,
  CaptureStatus,
  CaptureStatusResponse,
  CaptureSyncQueryRequest,
  CaptureSyncQueryResponse,
  ClientImage,
  DatasetVersionCreateRequest,
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
  LocalQueueStatus,
  ModelDeploymentCreateRequest,
  ModelStatus,
  ObjectCompleteRequest,
  ObjectCompleteResponse,
  ObjectReference,
  ObjectState,
  PreprocessQualityStatus,
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
  Traceparent,
  TrainingRunCreateRequest,
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
  approveModelDeployment: {
    method: "POST",
    path: "/api/v1/model-deployments/{model_deployment_id}/approvals",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
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
  getReviewWorkspace: {
    method: "GET",
    path: "/api/v1/review-tasks/{review_task_id}",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  getTrainingRun: {
    method: "GET",
    path: "/api/v1/training-runs/{training_run_id}",
    responseMediaCategory: "json",
    responseMediaTypes: ["application/json"],
  },
  listDetections: {
    method: "GET",
    path: "/api/v1/detections",
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
  queryCaptureSync: {
    method: "POST",
    path: "/api/v1/edge/sync/captures/query",
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
} as const satisfies Readonly<Record<string, {
  readonly method: string;
  readonly path: string;
  readonly responseMediaCategory: ApiResponseMediaCategory;
  readonly responseMediaTypes: readonly string[];
}>>;

export type ApiOperationId = keyof typeof API_OPERATION_METADATA;

export type ApproveModelDeploymentRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "model_deployment_id": Uuid; }>;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; readonly "If-Match": string; }>;
  readonly body: (ApprovalRequest);
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

export type GetReviewWorkspaceRequestEnvelope = Readonly<{
  readonly path: Readonly<{ readonly "review_task_id": Uuid; }>;
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

export type ListDetectionsRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: Readonly<{ readonly "algorithm_outcome"?: AlgorithmOutcome; readonly "business_disposition"?: BusinessDisposition; readonly "cursor"?: string; readonly "model_version"?: string; readonly "page_size"?: number; }>;
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

export type QueryCaptureSyncRequestEnvelope = Readonly<{
  readonly path?: never;
  readonly query?: never;
  readonly headers: Readonly<{ readonly "Idempotency-Key": string; }>;
  readonly body: (CaptureSyncQueryRequest);
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

export type ApiOperationRequestMap = Readonly<{
  readonly approveModelDeployment: ApproveModelDeploymentRequestEnvelope;
  readonly claimReviewTask: ClaimReviewTaskRequestEnvelope;
  readonly completeCaptureImage: CompleteCaptureImageRequestEnvelope;
  readonly completeReviewAnnotation: CompleteReviewAnnotationRequestEnvelope;
  readonly createAnnotationUploadTicket: CreateAnnotationUploadTicketRequestEnvelope;
  readonly createCapture: CreateCaptureRequestEnvelope;
  readonly createDatasetVersion: CreateDatasetVersionRequestEnvelope;
  readonly createImageAccessTicket: CreateImageAccessTicketRequestEnvelope;
  readonly createModelDeployment: CreateModelDeploymentRequestEnvelope;
  readonly createTrainingRun: CreateTrainingRunRequestEnvelope;
  readonly getDatasetVersion: GetDatasetVersionRequestEnvelope;
  readonly getDetection: GetDetectionRequestEnvelope;
  readonly getEdgeCapture: GetEdgeCaptureRequestEnvelope;
  readonly getInferenceReadiness: GetInferenceReadinessRequestEnvelope;
  readonly getReviewWorkspace: GetReviewWorkspaceRequestEnvelope;
  readonly getTrainingRun: GetTrainingRunRequestEnvelope;
  readonly listDetections: ListDetectionsRequestEnvelope;
  readonly listReviewTasks: ListReviewTasksRequestEnvelope;
  readonly listRuntimeModels: ListRuntimeModelsRequestEnvelope;
  readonly queryCaptureSync: QueryCaptureSyncRequestEnvelope;
  readonly releaseReviewTask: ReleaseReviewTaskRequestEnvelope;
  readonly renewCaptureImageUploadTicket: RenewCaptureImageUploadTicketRequestEnvelope;
  readonly reportDeviceHeartbeat: ReportDeviceHeartbeatRequestEnvelope;
  readonly retryDetection: RetryDetectionRequestEnvelope;
  readonly rollbackModelDeployment: RollbackModelDeploymentRequestEnvelope;
  readonly startDetectionAttempt: StartDetectionAttemptRequestEnvelope;
  readonly streamAuthorizedEvents: StreamAuthorizedEventsRequestEnvelope;
  readonly submitCapture: SubmitCaptureRequestEnvelope;
  readonly submitDetectionFailure: SubmitDetectionFailureRequestEnvelope;
  readonly submitDetectionResult: SubmitDetectionResultRequestEnvelope;
  readonly submitModelValidationDecision: SubmitModelValidationDecisionRequestEnvelope;
  readonly submitReview: SubmitReviewRequestEnvelope;
}>;

export interface ApiClient {
  approveModelDeployment(request: ApproveModelDeploymentRequestEnvelope): Promise<JsonObject>;
  claimReviewTask(request: ClaimReviewTaskRequestEnvelope): Promise<JsonObject>;
  completeCaptureImage(request: CompleteCaptureImageRequestEnvelope): Promise<JsonObject>;
  completeReviewAnnotation(request: CompleteReviewAnnotationRequestEnvelope): Promise<JsonObject>;
  createAnnotationUploadTicket(request: CreateAnnotationUploadTicketRequestEnvelope): Promise<JsonObject>;
  createCapture(request: CreateCaptureRequestEnvelope): Promise<JsonObject>;
  createDatasetVersion(request: CreateDatasetVersionRequestEnvelope): Promise<JsonObject>;
  createImageAccessTicket(request: CreateImageAccessTicketRequestEnvelope): Promise<JsonObject>;
  createModelDeployment(request: CreateModelDeploymentRequestEnvelope): Promise<JsonObject>;
  createTrainingRun(request: CreateTrainingRunRequestEnvelope): Promise<JsonObject>;
  getDatasetVersion(request: GetDatasetVersionRequestEnvelope): Promise<JsonObject>;
  getDetection(request: GetDetectionRequestEnvelope): Promise<JsonObject>;
  getEdgeCapture(request: GetEdgeCaptureRequestEnvelope): Promise<JsonObject>;
  getInferenceReadiness(request?: GetInferenceReadinessRequestEnvelope): Promise<JsonObject>;
  getReviewWorkspace(request: GetReviewWorkspaceRequestEnvelope): Promise<JsonObject>;
  getTrainingRun(request: GetTrainingRunRequestEnvelope): Promise<JsonObject>;
  listDetections(request?: ListDetectionsRequestEnvelope): Promise<JsonObject>;
  listReviewTasks(request?: ListReviewTasksRequestEnvelope): Promise<JsonObject>;
  listRuntimeModels(request?: ListRuntimeModelsRequestEnvelope): Promise<JsonObject>;
  queryCaptureSync(request: QueryCaptureSyncRequestEnvelope): Promise<JsonObject>;
  releaseReviewTask(request: ReleaseReviewTaskRequestEnvelope): Promise<JsonObject>;
  renewCaptureImageUploadTicket(request: RenewCaptureImageUploadTicketRequestEnvelope): Promise<JsonObject>;
  reportDeviceHeartbeat(request: ReportDeviceHeartbeatRequestEnvelope): Promise<JsonObject>;
  retryDetection(request: RetryDetectionRequestEnvelope): Promise<JsonObject>;
  rollbackModelDeployment(request: RollbackModelDeploymentRequestEnvelope): Promise<JsonObject>;
  startDetectionAttempt(request: StartDetectionAttemptRequestEnvelope): Promise<JsonObject>;
  streamAuthorizedEvents(request?: StreamAuthorizedEventsRequestEnvelope): Promise<JsonObject>;
  submitCapture(request: SubmitCaptureRequestEnvelope): Promise<JsonObject>;
  submitDetectionFailure(request: SubmitDetectionFailureRequestEnvelope): Promise<JsonObject>;
  submitDetectionResult(request: SubmitDetectionResultRequestEnvelope): Promise<JsonObject>;
  submitModelValidationDecision(request: SubmitModelValidationDecisionRequestEnvelope): Promise<JsonObject>;
  submitReview(request: SubmitReviewRequestEnvelope): Promise<JsonObject>;
}
