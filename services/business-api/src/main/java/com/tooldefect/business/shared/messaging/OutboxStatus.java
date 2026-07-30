package com.tooldefect.business.shared.messaging;

public enum OutboxStatus {
    NEW,
    CLAIMED,
    PUBLISHED,
    FAILED,
    DEAD
}
