// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 1；源哈希: f72a5a3390cfe2d9530d4d12b3bb2d572a57fbbb290c10bf886c1479509935fb
package local.tooldefect.contracts;

public record ObjectReference(String bucket, String objectKey, String sha256, long sizeBytes, String mediaType, String objectVersion) {}
