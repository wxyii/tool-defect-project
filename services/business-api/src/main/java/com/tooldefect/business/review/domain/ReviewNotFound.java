package com.tooldefect.business.review.domain;

public final class ReviewNotFound extends RuntimeException {
    public ReviewNotFound(String message) {
        super(message);
    }
}
