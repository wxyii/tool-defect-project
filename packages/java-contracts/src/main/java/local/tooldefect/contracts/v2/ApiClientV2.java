// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 2；源哈希: 22c752871f6e08eabb41421367fff400af7513cc7fdfc2a1a5cab551308ca2f9
package local.tooldefect.contracts.v2;

import java.util.Map;

public interface ApiClientV2 {
    Map<String, Object> addDetectionBatchItemV2(Map<String, Object> request);
    Map<String, Object> approveModelActivationRequestV2(Map<String, Object> request);
    Map<String, Object> completeDetectionBatchItemUploadV2(Map<String, Object> request);
    Map<String, Object> completeModelUploadSessionV2(Map<String, Object> request);
    Map<String, Object> createAdminFeedbackV2(Map<String, Object> request);
    Map<String, Object> createDetectionBatchV2(Map<String, Object> request);
    Map<String, Object> createModelActivationRequestV2(Map<String, Object> request);
    Map<String, Object> createModelRollbackRequestV2(Map<String, Object> request);
    Map<String, Object> createModelUploadSessionV2(Map<String, Object> request);
    Map<String, Object> createProductionDetectionItemV2(Map<String, Object> request);
    Map<String, Object> createSampleCandidateV2(Map<String, Object> request);
    Map<String, Object> createSampleExportDownloadTicketV2(Map<String, Object> request);
    Map<String, Object> createSampleExportV2(Map<String, Object> request);
    Map<String, Object> decideSampleCandidateV2(Map<String, Object> request);
    Map<String, Object> deleteDetectionBatchItemV2(Map<String, Object> request);
    Map<String, Object> getDetectionBatchItemV2(Map<String, Object> request);
    Map<String, Object> getDetectionBatchV2(Map<String, Object> request);
    Map<String, Object> getManualDetectionCapabilitiesV2(Map<String, Object> request);
    Map<String, Object> getModelUploadSessionV2(Map<String, Object> request);
    Map<String, Object> getSampleExportV2(Map<String, Object> request);
    Map<String, Object> listAdminDetectionItemsV2(Map<String, Object> request);
    Map<String, Object> listDetectionBatchesV2(Map<String, Object> request);
    Map<String, Object> listModelVersionsV2(Map<String, Object> request);
    Map<String, Object> listSampleCandidatesV2(Map<String, Object> request);
    Map<String, Object> putQuickReviewV2(Map<String, Object> request);
    Map<String, Object> submitDetectionBatchV2(Map<String, Object> request);
}
