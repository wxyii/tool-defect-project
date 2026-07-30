package com.tooldefect.business.review.domain;

public final class ReviewConflict extends RuntimeException {
    public ReviewConflict(String message) {
        super(message);
    }
}
