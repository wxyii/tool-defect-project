package com.tooldefect.business.detection.domain;

public enum ExecutionStatus {
    QUEUED,
    RUNNING,
    SUCCEEDED,
    RETRY_WAIT,
    DEAD
}
