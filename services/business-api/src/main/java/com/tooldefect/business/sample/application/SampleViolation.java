package com.tooldefect.business.sample.application;

import com.tooldefect.business.shared.domain.DomainViolation;

public final class SampleViolation extends DomainViolation {
    private final Kind kind;

    public SampleViolation(Kind kind, String message) {
        super(message);
        this.kind = kind;
    }

    public Kind kind() {
        return kind;
    }

    public enum Kind {
        NOT_FOUND, CONFLICT, INTEGRITY, DISABLED, HOLD, EXPIRED
    }
}
