package com.tooldefect.business.storage.domain;

import com.tooldefect.business.shared.domain.DomainViolation;

public final class StorageAccessDenied extends DomainViolation {
    public StorageAccessDenied(String message) {
        super(message);
    }
}
