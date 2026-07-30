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
  AlgorithmOutcome,
  AttemptStatus,
  BusinessDisposition,
  CaptureStatusResponse,
  CaptureStatus,
  DetectionDetail,
  DetectionPage,
  DetectionSummary,
  ExecutionStatus,
  ImageAccessTicketResponse,
  ImageReference,
  ImageKind,
  LocalQueueStatus,
  ModelStatus,
  ObjectCompleteResponse,
  ObjectReference,
  ObjectState,
  PreprocessQualityStatus,
  ReviewStatus,
  ReviewSubmissionRequest,
  ReviewSubmissionResponse,
  ReviewTask,
  ReviewTaskPage,
  ReviewWorkspace,
  UploadTicketResponse,
  UtcTimestamp,
  Uuid,
} from '@contracts/index'

export type {
  ApiClient as GeneratedApiClient,
  JsonObject,
} from '@contracts/client'
