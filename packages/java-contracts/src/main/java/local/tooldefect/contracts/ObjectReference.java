// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 1；源哈希: ed7e2561eaf84715c91514cec5e470ae170c3e94819820826fe34286543d7bde
package local.tooldefect.contracts;

public record ObjectReference(String bucket, String objectKey, String sha256, long sizeBytes, String mediaType, String objectVersion) {}
