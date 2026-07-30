// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 1；源哈希: 3578f82330fbba2e9e500f67fd1b574296707f5b20058cae9d70ed9bc3868ce5
package local.tooldefect.contracts;

public record ObjectReference(String bucket, String objectKey, String sha256, long sizeBytes, String mediaType, String objectVersion) {}
