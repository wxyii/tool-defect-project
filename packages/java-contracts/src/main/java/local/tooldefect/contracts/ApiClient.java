// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 1；源哈希: 6fc5d9465464faf374bfa54d8f20849623f912a6c3d88fdbe92ca47fba49e361
package local.tooldefect.contracts;

import java.util.Map;

public interface ApiClient {
    Map<String, Object> approveModelDeployment(Map<String, Object> request);
    Map<String, Object> claimReviewTask(Map<String, Object> request);
    Map<String, Object> completeCaptureImage(Map<String, Object> request);
    Map<String, Object> createAnnotationUploadTicket(Map<String, Object> request);
    Map<String, Object> createCapture(Map<String, Object> request);
    Map<String, Object> createDatasetVersion(Map<String, Object> request);
    Map<String, Object> createImageAccessTicket(Map<String, Object> request);
    Map<String, Object> createModelDeployment(Map<String, Object> request);
    Map<String, Object> createTrainingRun(Map<String, Object> request);
    Map<String, Object> getDatasetVersion(Map<String, Object> request);
    Map<String, Object> getDetection(Map<String, Object> request);
    Map<String, Object> getEdgeCapture(Map<String, Object> request);
    Map<String, Object> getInferenceReadiness(Map<String, Object> request);
    Map<String, Object> getTrainingRun(Map<String, Object> request);
    Map<String, Object> listDetections(Map<String, Object> request);
    Map<String, Object> listReviewTasks(Map<String, Object> request);
    Map<String, Object> listRuntimeModels(Map<String, Object> request);
    Map<String, Object> queryCaptureSync(Map<String, Object> request);
    Map<String, Object> releaseReviewTask(Map<String, Object> request);
    Map<String, Object> renewCaptureImageUploadTicket(Map<String, Object> request);
    Map<String, Object> reportDeviceHeartbeat(Map<String, Object> request);
    Map<String, Object> retryDetection(Map<String, Object> request);
    Map<String, Object> rollbackModelDeployment(Map<String, Object> request);
    Map<String, Object> startDetectionAttempt(Map<String, Object> request);
    Map<String, Object> streamAuthorizedEvents(Map<String, Object> request);
    Map<String, Object> submitCapture(Map<String, Object> request);
    Map<String, Object> submitDetectionFailure(Map<String, Object> request);
    Map<String, Object> submitDetectionResult(Map<String, Object> request);
    Map<String, Object> submitModelValidationDecision(Map<String, Object> request);
    Map<String, Object> submitReview(Map<String, Object> request);
}
