package com.tooldefect.business.deployment.application;

import com.tooldefect.business.shared.domain.DomainViolation;

/** 目标模型在独立回滚槽完成验签、预热和健康检查后的不可变证据摘要。 */
public record RollbackRuntimeEvidence(
        String rollbackEvidenceSha256,
        boolean packageSignatureVerified,
        boolean prewarmed,
        boolean healthReady) {

    public RollbackRuntimeEvidence {
        if (rollbackEvidenceSha256 == null || !rollbackEvidenceSha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("回滚运行证据摘要不合法");
        }
        if (!packageSignatureVerified || !prewarmed || !healthReady) {
            throw new DomainViolation("回滚模型包验签、预热和健康检查必须全部通过");
        }
    }
}
