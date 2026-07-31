/**
 * 前端对冻结契约生成包的唯一入口。
 *
 * 网络对象和状态类型均从 `contracts/` 生成，手写请求层只负责认证、重试、
 * 请求标识与错误转换，不复制领域枚举。
 */
export {
  CONTRACT_MAJOR_VERSION,
  CONTRACT_SOURCE_SHA256,
} from '@contracts/index'

export type {
  Acknowledgement,
  AlgorithmOutcome,
  ApprovalRequest,
  AttemptStatus,
  AsyncAccepted,
  BusinessDisposition,
  CaptureStatusResponse,
  CaptureStatus,
  DatasetVersionDiff,
  DatasetVersionDiffItem,
  DatasetVersionPage,
  DatasetVersionSummary,
  DetectionDetail,
  DetectionPage,
  DetectionSummary,
  ExecutionStatus,
  ImageAccessTicketResponse,
  ImageReference,
  ImageKind,
  LocalQueueStatus,
  ModelDeploymentCreateRequest,
  ModelDeploymentResponse,
  ModelStatus,
  ModelVersionPage,
  ModelVersionRegisterRequest,
  ModelVersionRegistrationResponse,
  ModelVersionResponse,
  ModelVersionSummary,
  ObjectCompleteResponse,
  ObjectReference,
  ObjectState,
  PreprocessQualityStatus,
  QualityMetricReason,
  QualityMetrics,
  ReviewStatus,
  ReviewSubmissionRequest,
  ReviewSubmissionResponse,
  ReviewTask,
  ReviewTaskPage,
  ReviewWorkspace,
  RollbackRequest,
  TrainingRunCreateRequest,
  UploadTicketResponse,
  UtcTimestamp,
  Uuid,
  ValidationDecisionRequest,
  Version,
  VersionedResource,
} from '@contracts/index'

export type {
  ApiClient as GeneratedApiClient,
  JsonObject,
} from '@contracts/client'
