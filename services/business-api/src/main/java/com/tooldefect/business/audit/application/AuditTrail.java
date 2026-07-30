package com.tooldefect.business.audit.application;

import com.tooldefect.business.audit.domain.AuditRecord;

public interface AuditTrail {
    void append(AuditRecord record);
}
