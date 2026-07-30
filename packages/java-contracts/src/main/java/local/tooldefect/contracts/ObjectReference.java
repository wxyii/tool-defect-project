// 由 tools/generate-contracts/generate.py 生成；禁止手工编辑。
// 契约主版本: 1；源哈希: 6fc5d9465464faf374bfa54d8f20849623f912a6c3d88fdbe92ca47fba49e361
package local.tooldefect.contracts;

public record ObjectReference(String bucket, String objectKey, String sha256, long sizeBytes, String mediaType, String objectVersion) {}
