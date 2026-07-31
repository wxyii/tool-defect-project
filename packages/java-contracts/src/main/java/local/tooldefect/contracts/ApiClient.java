// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 1；源哈希: 698d11ac5202bb62df31a09ed1c46be7280d905bc497c612fa9ab557e35b26cc
package local.tooldefect.contracts;

import java.util.Map;

public interface ApiClient {
    Map<String, Object> approveModelDeployment(Map<String, Object> request);
    Map<String, Object> changeLocalPassword(Map<String, Object> request);
    Map<String, Object> claimReviewTask(Map<String, Object> request);
    Map<String, Object> completeCaptureImage(Map<String, Object> request);
    Map<String, Object> completeReviewAnnotation(Map<String, Object> request);
    Map<String, Object> createAnnotationUploadTicket(Map<String, Object> request);
    Map<String, Object> createCapture(Map<String, Object> request);
    Map<String, Object> createDatasetVersion(Map<String, Object> request);
    Map<String, Object> createImageAccessTicket(Map<String, Object> request);
    Map<String, Object> createLocalUser(Map<String, Object> request);
    Map<String, Object> createModelDeployment(Map<String, Object> request);
    Map<String, Object> createTrainingRun(Map<String, Object> request);
    Map<String, Object> diffDatasetVersions(Map<String, Object> request);
    Map<String, Object> getCsrfToken(Map<String, Object> request);
    Map<String, Object> getDatasetVersion(Map<String, Object> request);
    Map<String, Object> getDetection(Map<String, Object> request);
    Map<String, Object> getEdgeCapture(Map<String, Object> request);
    Map<String, Object> getInferenceReadiness(Map<String, Object> request);
    Map<String, Object> getLocalUserSession(Map<String, Object> request);
    Map<String, Object> getModelDeployment(Map<String, Object> request);
    Map<String, Object> getModelVersion(Map<String, Object> request);
    Map<String, Object> getQualityMetrics(Map<String, Object> request);
    Map<String, Object> getReviewWorkspace(Map<String, Object> request);
    Map<String, Object> getTrainingRun(Map<String, Object> request);
    Map<String, Object> listDatasetVersions(Map<String, Object> request);
    Map<String, Object> listDetections(Map<String, Object> request);
    Map<String, Object> listLocalUsers(Map<String, Object> request);
    Map<String, Object> listModelVersions(Map<String, Object> request);
    Map<String, Object> listReviewTasks(Map<String, Object> request);
    Map<String, Object> listRuntimeModels(Map<String, Object> request);
    Map<String, Object> loginLocalUser(Map<String, Object> request);
    Map<String, Object> logoutLocalUser(Map<String, Object> request);
    Map<String, Object> queryCaptureSync(Map<String, Object> request);
    Map<String, Object> registerModelVersion(Map<String, Object> request);
    Map<String, Object> releaseReviewTask(Map<String, Object> request);
    Map<String, Object> renewCaptureImageUploadTicket(Map<String, Object> request);
    Map<String, Object> reportDeviceHeartbeat(Map<String, Object> request);
    Map<String, Object> resetLocalUserPassword(Map<String, Object> request);
    Map<String, Object> retryDetection(Map<String, Object> request);
    Map<String, Object> rollbackModelDeployment(Map<String, Object> request);
    Map<String, Object> startDetectionAttempt(Map<String, Object> request);
    Map<String, Object> streamAuthorizedEvents(Map<String, Object> request);
    Map<String, Object> submitCapture(Map<String, Object> request);
    Map<String, Object> submitDetectionFailure(Map<String, Object> request);
    Map<String, Object> submitDetectionResult(Map<String, Object> request);
    Map<String, Object> submitModelValidationDecision(Map<String, Object> request);
    Map<String, Object> submitReview(Map<String, Object> request);
    Map<String, Object> updateLocalUserRoles(Map<String, Object> request);
    Map<String, Object> updateLocalUserStatus(Map<String, Object> request);
    Map<String, Object> updateTrainingRunStatus(Map<String, Object> request);
}
