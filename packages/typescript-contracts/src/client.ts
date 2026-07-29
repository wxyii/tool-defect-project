// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 1；源哈希: 186ea774bef9ecad130bacc65e1e35cc88ed59f479bd8ce14ecf19a84b300795
export type JsonObject = Readonly<Record<string, unknown>>;

export interface ApiClient {
  approveModelDeployment(request?: JsonObject): Promise<JsonObject>;
  claimReviewTask(request?: JsonObject): Promise<JsonObject>;
  completeCaptureImage(request?: JsonObject): Promise<JsonObject>;
  createAnnotationUploadTicket(request?: JsonObject): Promise<JsonObject>;
  createCapture(request?: JsonObject): Promise<JsonObject>;
  createDatasetVersion(request?: JsonObject): Promise<JsonObject>;
  createImageAccessTicket(request?: JsonObject): Promise<JsonObject>;
  createModelDeployment(request?: JsonObject): Promise<JsonObject>;
  createTrainingRun(request?: JsonObject): Promise<JsonObject>;
  getDatasetVersion(request?: JsonObject): Promise<JsonObject>;
  getDetection(request?: JsonObject): Promise<JsonObject>;
  getEdgeCapture(request?: JsonObject): Promise<JsonObject>;
  getInferenceReadiness(request?: JsonObject): Promise<JsonObject>;
  getTrainingRun(request?: JsonObject): Promise<JsonObject>;
  listDetections(request?: JsonObject): Promise<JsonObject>;
  listReviewTasks(request?: JsonObject): Promise<JsonObject>;
  listRuntimeModels(request?: JsonObject): Promise<JsonObject>;
  queryCaptureSync(request?: JsonObject): Promise<JsonObject>;
  releaseReviewTask(request?: JsonObject): Promise<JsonObject>;
  reportDeviceHeartbeat(request?: JsonObject): Promise<JsonObject>;
  retryDetection(request?: JsonObject): Promise<JsonObject>;
  rollbackModelDeployment(request?: JsonObject): Promise<JsonObject>;
  startDetectionAttempt(request?: JsonObject): Promise<JsonObject>;
  streamAuthorizedEvents(request?: JsonObject): Promise<JsonObject>;
  submitCapture(request?: JsonObject): Promise<JsonObject>;
  submitDetectionFailure(request?: JsonObject): Promise<JsonObject>;
  submitDetectionResult(request?: JsonObject): Promise<JsonObject>;
  submitModelValidationDecision(request?: JsonObject): Promise<JsonObject>;
  submitReview(request?: JsonObject): Promise<JsonObject>;
}
