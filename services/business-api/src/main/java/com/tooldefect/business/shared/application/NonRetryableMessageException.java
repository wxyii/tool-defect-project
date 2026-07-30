package com.tooldefect.business.shared.application;

public final class NonRetryableMessageException extends RuntimeException {
    public NonRetryableMessageException(String message) {
        super(message);
    }

    public NonRetryableMessageException(String message, Throwable cause) {
        super(message, cause);
    }
}
