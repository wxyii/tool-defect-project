package com.tooldefect.business.detectionbatch.application;

import com.tooldefect.business.shared.domain.DomainViolation;

public class ManualDetectionViolation extends DomainViolation {
    private final Kind kind;
    public ManualDetectionViolation(Kind kind,String message){super(message);this.kind=kind;}
    public Kind kind(){return kind;}
    public enum Kind { NOT_FOUND, DENIED, CONFLICT, INTEGRITY, EXPIRED, DISABLED }
}
