import type { ModelVersionRegisterRequest } from '@/api/generated'

export interface ModelRegistrationDraft {
  readonly modelId: string
  readonly trainingRunId: string
  readonly datasetVersionId: string
  readonly registryName: string
  readonly registryVersion: string
  readonly artifactBucket: string
  readonly artifactObjectKey: string
  readonly artifactSha256: string
  readonly sbomSha256: string
  readonly signatureKeyId: string
  readonly inputSpec: string
  readonly outputSpec: string
  readonly evaluationReportSha256: string
  readonly thresholdGateSha256: string
}

export class ModelRegistrationInputError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ModelRegistrationInputError'
  }
}

export function buildModelRegistrationRequest(
  draft: ModelRegistrationDraft,
): ModelVersionRegisterRequest {
  const modelId = uuid(draft.modelId, '模型')
  const trainingRunId = uuid(draft.trainingRunId, '训练运行')
  const datasetVersionId = uuid(draft.datasetVersionId, '数据集版本')
  const registryName = text(draft.registryName, '注册表名称', 256)
  const registryVersion = text(draft.registryVersion, '注册表版本', 128)
  const artifactBucket = text(draft.artifactBucket, '模型制品桶', 128)
  const artifactObjectKey = text(draft.artifactObjectKey, '模型包对象键', 1024)
  const artifactSha256 = sha256(draft.artifactSha256, '模型包')
  const sbomSha256 = sha256(draft.sbomSha256, 'SBOM')
  const signatureKeyId = text(draft.signatureKeyId, '签名密钥 ID', 256)
  const evaluationReportSha256 = sha256(
    draft.evaluationReportSha256,
    '评估报告',
  )
  const thresholdGateSha256 = sha256(
    draft.thresholdGateSha256,
    '门槛报告',
  )

  return Object.freeze({
    model_id: modelId,
    training_run_id: trainingRunId,
    dataset_version_id: datasetVersionId,
    registry_name: registryName,
    registry_version: registryVersion,
    artifact_bucket: artifactBucket,
    artifact_object_key: artifactObjectKey,
    artifact_sha256: artifactSha256,
    sbom_sha256: sbomSha256,
    signature_key_id: signatureKeyId,
    input_spec: jsonObject(draft.inputSpec, '输入规格'),
    output_spec: jsonObject(draft.outputSpec, '输出规格'),
    evaluation_summary: Object.freeze({
      evaluation_report_sha256: evaluationReportSha256,
      threshold_gate_sha256: thresholdGateSha256,
    }),
  }) as ModelVersionRegisterRequest
}

function uuid(value: string, label: string): string {
  const normalized = value.trim()
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
      .test(normalized)
  ) {
    throw new ModelRegistrationInputError(`${label} ID 必须是 UUID`)
  }
  return normalized
}

function sha256(value: string, label: string): string {
  const normalized = value.trim()
  if (!/^[0-9a-f]{64}$/.test(normalized)) {
    throw new ModelRegistrationInputError(
      `${label} SHA-256 必须是 64 位小写十六进制`,
    )
  }
  return normalized
}

function text(value: string, label: string, maximum: number): string {
  const normalized = value.trim()
  if (normalized.length === 0 || normalized.length > maximum) {
    throw new ModelRegistrationInputError(
      `${label}不能为空且不能超过 ${maximum} 个字符`,
    )
  }
  return normalized
}

function jsonObject(
  value: string,
  label: string,
): Readonly<Record<string, unknown>> {
  let parsed: unknown
  try {
    parsed = JSON.parse(value)
  } catch {
    throw new ModelRegistrationInputError(`${label}必须是合法 JSON 对象`)
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new ModelRegistrationInputError(`${label}顶层必须是 JSON 对象`)
  }
  return Object.freeze({ ...(parsed as Record<string, unknown>) })
}
