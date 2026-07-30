package com.tooldefect.business.shared.domain;

public final class IdempotencyConflict extends DomainViolation {
    public IdempotencyConflict(String message) {
        super(message);
    }
}
