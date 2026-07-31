package com.tooldefect.business.deployment.application;

import com.tooldefect.business.shared.domain.DomainViolation;

/** 推理双槽返回的不可变运行证据摘要；业务库不接受单独的“已验签”自声明。 */
public record DeploymentRuntimeEvidence(
        String warmupEvidenceSha256,
        String metricsGateSha256,
        boolean packageSignatureVerified,
        boolean prewarmed,
        boolean healthReady) {

    public DeploymentRuntimeEvidence {
        if (warmupEvidenceSha256 == null || !warmupEvidenceSha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("预热运行证据摘要不合法");
        }
        if (metricsGateSha256 == null || !metricsGateSha256.matches("[0-9a-f]{64}")) {
            throw new DomainViolation("灰度门槛运行证据摘要不合法");
        }
        if (!packageSignatureVerified || !prewarmed || !healthReady) {
            throw new DomainViolation("模型包验签、预热和健康检查必须全部通过");
        }
    }
}
