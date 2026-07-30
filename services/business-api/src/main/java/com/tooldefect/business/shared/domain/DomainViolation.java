package com.tooldefect.business.shared.domain;

/** 不依赖框架的领域约束异常。 */
public class DomainViolation extends RuntimeException {
    public DomainViolation(String message) {
        super(message);
    }

    public DomainViolation(String message, Throwable cause) {
        super(message, cause);
    }
}
