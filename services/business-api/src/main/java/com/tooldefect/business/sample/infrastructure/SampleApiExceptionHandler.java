package com.tooldefect.business.sample.infrastructure;

import java.util.Map;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

import com.tooldefect.business.sample.api.SampleLibraryController;
import com.tooldefect.business.sample.application.SampleViolation;
import com.tooldefect.business.shared.api.ContractValues.ContractInputViolation;
import com.tooldefect.business.shared.api.StandardErrorFactory;
import com.tooldefect.business.shared.domain.IdempotencyConflict;

@RestControllerAdvice(assignableTypes = SampleLibraryController.class)
public final class SampleApiExceptionHandler {
    @ExceptionHandler({MissingRequestHeaderException.class, MethodArgumentTypeMismatchException.class})
    ResponseEntity<Map<String, Object>> malformed(
            Exception error, HttpServletRequest request) {
        return response(HttpStatus.BAD_REQUEST, "TD-API-VALIDATION-001", false, error, request);
    }

    @ExceptionHandler(ContractInputViolation.class)
    ResponseEntity<Map<String, Object>> invalid(
            RuntimeException error, HttpServletRequest request) {
        return response(HttpStatus.UNPROCESSABLE_CONTENT, "TD-API-VALIDATION-001", false,
            error, request);
    }

    @ExceptionHandler(IdempotencyConflict.class)
    ResponseEntity<Map<String, Object>> idempotency(
            RuntimeException error, HttpServletRequest request) {
        return response(HttpStatus.CONFLICT, "TD-IDEMPOTENCY-CONFLICT-001", false, error, request);
    }

    @ExceptionHandler(SampleViolation.class)
    ResponseEntity<Map<String, Object>> sample(
            SampleViolation error, HttpServletRequest request) {
        return switch (error.kind()) {
            case NOT_FOUND -> response(HttpStatus.NOT_FOUND, "TD-SAMPLE-NOT-FOUND-001", false, error, request);
            case CONFLICT -> response(HttpStatus.CONFLICT, "TD-SAMPLE-CONFLICT-001", false, error, request);
            case INTEGRITY -> response(HttpStatus.UNPROCESSABLE_CONTENT, "TD-SAMPLE-INTEGRITY-001", false, error, request);
            case DISABLED -> response(HttpStatus.GONE, "TD-LEGACY-FEATURE-RETIRED", false, error, request);
            case HOLD -> response(HttpStatus.SERVICE_UNAVAILABLE, "TD-SAMPLE-HOLD-001", true, error, request);
            case EXPIRED -> response(HttpStatus.CONFLICT, "TD-SAMPLE-EXPIRED-001", true, error, request);
        };
    }

    private static ResponseEntity<Map<String, Object>> response(
            HttpStatus status, String code, boolean retryable, Exception error,
            HttpServletRequest request) {
        return ResponseEntity.status(status).body(
            StandardErrorFactory.body(request, code, error.getMessage(), retryable));
    }
}
