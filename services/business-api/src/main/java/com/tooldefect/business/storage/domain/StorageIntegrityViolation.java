package com.tooldefect.business.storage.domain;

import com.tooldefect.business.shared.domain.DomainViolation;

/** 需要持久化隔离；调用端只能按明确上限执行受控重传的内容完整性失败。 */
public final class StorageIntegrityViolation extends DomainViolation {
    public StorageIntegrityViolation(String message) {
        super(message);
    }

    public StorageIntegrityViolation(String message, Throwable cause) {
        super(message, cause);
    }
}
