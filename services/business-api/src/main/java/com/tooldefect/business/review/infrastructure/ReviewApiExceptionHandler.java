package com.tooldefect.business.review.infrastructure;

import java.util.Map;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

import com.tooldefect.business.review.api.ReviewController;
import com.tooldefect.business.review.domain.ReviewAccessDenied;
import com.tooldefect.business.review.domain.ReviewConflict;
import com.tooldefect.business.review.domain.ReviewNotFound;
import com.tooldefect.business.detection.domain.DetectionNotFound;
import com.tooldefect.business.shared.api.ContractValues;
import com.tooldefect.business.shared.api.StandardErrorFactory;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.domain.IdempotencyConflict;
import com.tooldefect.business.storage.domain.StorageAccessDenied;
import com.tooldefect.business.storage.domain.StorageIntegrityViolation;
import com.tooldefect.business.storage.domain.StorageTicketExpired;

@RestControllerAdvice(assignableTypes = ReviewController.class)
public final class ReviewApiExceptionHandler {
    @ExceptionHandler({
        MissingRequestHeaderException.class,
        MethodArgumentTypeMismatchException.class,
        HttpMessageNotReadableException.class
    })
    ResponseEntity<Map<String, Object>> malformed(
            Exception error,
            HttpServletRequest request) {
        return error(
            HttpStatus.BAD_REQUEST,
            "TD-API-VALIDATION-001",
            error,
            request
        );
    }

    @ExceptionHandler({
        ContractValues.ContractInputViolation.class,
        DomainViolation.class
    })
    ResponseEntity<Map<String, Object>> invalid(
            RuntimeException error,
            HttpServletRequest request) {
        return error(
            HttpStatus.UNPROCESSABLE_CONTENT,
            "TD-REVIEW-VALIDATION-001",
            error,
            request
        );
    }

    @ExceptionHandler({
        ReviewAccessDenied.class,
        StorageAccessDenied.class
    })
    ResponseEntity<Map<String, Object>> forbidden(
            RuntimeException error,
            HttpServletRequest request) {
        return error(
            HttpStatus.FORBIDDEN,
            "TD-SECURITY-AUTHORIZATION-001",
            error,
            request
        );
    }

    @ExceptionHandler({
        ReviewNotFound.class,
        DetectionNotFound.class
    })
    ResponseEntity<Map<String, Object>> missing(
            RuntimeException error,
            HttpServletRequest request) {
        return error(
            HttpStatus.NOT_FOUND,
            "TD-REVIEW-NOT-FOUND-001",
            error,
            request
        );
    }

    @ExceptionHandler({
        ReviewConflict.class,
        IdempotencyConflict.class,
        StorageTicketExpired.class
    })
    ResponseEntity<Map<String, Object>> conflict(
            RuntimeException error,
            HttpServletRequest request) {
        return error(
            HttpStatus.CONFLICT,
            "TD-REVIEW-CONFLICT-001",
            error,
            request
        );
    }

    @ExceptionHandler(StorageIntegrityViolation.class)
    ResponseEntity<Map<String, Object>> storageIntegrity(
            StorageIntegrityViolation error,
            HttpServletRequest request) {
        return error(
            HttpStatus.UNPROCESSABLE_CONTENT,
            "TD-STORAGE-INTEGRITY-001",
            error,
            request
        );
    }

    private static ResponseEntity<Map<String, Object>> error(
            HttpStatus status,
            String code,
            Exception error,
            HttpServletRequest request) {
        return ResponseEntity.status(status).body(StandardErrorFactory.body(
            request,
            code,
            error.getMessage(),
            false
        ));
    }
}
