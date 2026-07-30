package com.tooldefect.business.storage.domain;

import com.tooldefect.business.shared.domain.DomainViolation;

/** 上传票据过期；调用方必须申请新票据，不能重用旧地址。 */
public final class StorageTicketExpired extends DomainViolation {
    public StorageTicketExpired(String message) {
        super(message);
    }
}
