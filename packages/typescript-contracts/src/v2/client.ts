// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 2；源哈希: ff943178ec32e8d1e936321170d1a28f70eab0edcd15a37884c81f148abb5ad4
export type JsonObject = Readonly<Record<string, unknown>>;

export interface ApiClientV2 {
  addDetectionBatchItemV2(request?: JsonObject): Promise<JsonObject>;
  approveModelActivationRequestV2(request?: JsonObject): Promise<JsonObject>;
  completeDetectionBatchItemUploadV2(request?: JsonObject): Promise<JsonObject>;
  completeModelUploadSessionV2(request?: JsonObject): Promise<JsonObject>;
  createAdminFeedbackV2(request?: JsonObject): Promise<JsonObject>;
  createDetectionBatchV2(request?: JsonObject): Promise<JsonObject>;
  createModelActivationRequestV2(request?: JsonObject): Promise<JsonObject>;
  createModelRollbackRequestV2(request?: JsonObject): Promise<JsonObject>;
  createModelUploadSessionV2(request?: JsonObject): Promise<JsonObject>;
  createProductionDetectionItemV2(request?: JsonObject): Promise<JsonObject>;
  createSampleCandidateV2(request?: JsonObject): Promise<JsonObject>;
  createSampleExportDownloadTicketV2(request?: JsonObject): Promise<JsonObject>;
  createSampleExportV2(request?: JsonObject): Promise<JsonObject>;
  createSampleExternalReceiptV2(request?: JsonObject): Promise<JsonObject>;
  decideSampleCandidateV2(request?: JsonObject): Promise<JsonObject>;
  deleteDetectionBatchItemV2(request?: JsonObject): Promise<JsonObject>;
  getDetectionBatchItemV2(request?: JsonObject): Promise<JsonObject>;
  getDetectionBatchV2(request?: JsonObject): Promise<JsonObject>;
  getManualDetectionCapabilitiesV2(request?: JsonObject): Promise<JsonObject>;
  getModelUploadSessionV2(request?: JsonObject): Promise<JsonObject>;
  getSampleExportV2(request?: JsonObject): Promise<JsonObject>;
  listAdminDetectionItemsV2(request?: JsonObject): Promise<JsonObject>;
  listDetectionBatchesV2(request?: JsonObject): Promise<JsonObject>;
  listModelVersionsV2(request?: JsonObject): Promise<JsonObject>;
  listSampleCandidatesV2(request?: JsonObject): Promise<JsonObject>;
  putQuickReviewV2(request?: JsonObject): Promise<JsonObject>;
  renewDetectionBatchItemUploadV2(request?: JsonObject): Promise<JsonObject>;
  submitDetectionBatchV2(request?: JsonObject): Promise<JsonObject>;
}
