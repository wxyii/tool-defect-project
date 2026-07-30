package com.tooldefect.business.review.domain;

public final class ReviewAccessDenied extends RuntimeException {
    public ReviewAccessDenied(String message) {
        super(message);
    }
}
