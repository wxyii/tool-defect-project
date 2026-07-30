package com.tooldefect.business.capture.infrastructure;

import java.util.Map;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

import com.tooldefect.business.capture.api.CaptureController;
import com.tooldefect.business.shared.api.ContractValues;
import com.tooldefect.business.shared.api.StandardErrorFactory;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.domain.IdempotencyConflict;
import com.tooldefect.business.storage.domain.StorageAccessDenied;
import com.tooldefect.business.storage.domain.StorageIntegrityViolation;
import com.tooldefect.business.storage.domain.StorageTicketExpired;

@RestControllerAdvice(assignableTypes = CaptureController.class)
public final class CaptureApiExceptionHandler {
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
            false,
            error,
            request
        );
    }

    @ExceptionHandler(ContractValues.ContractInputViolation.class)
    ResponseEntity<Map<String, Object>> invalid(
            RuntimeException error,
            HttpServletRequest request) {
        return error(
            HttpStatus.UNPROCESSABLE_CONTENT,
            "TD-API-VALIDATION-001",
            false,
            error,
            request
        );
    }

    @ExceptionHandler({
        CaptureController.CaptureIdentityViolation.class,
        StorageAccessDenied.class
    })
    ResponseEntity<Map<String, Object>> denied(
            RuntimeException error,
            HttpServletRequest request) {
        return error(
            HttpStatus.FORBIDDEN,
            "TD-SECURITY-AUTHORIZATION-001",
            false,
            error,
            request
        );
    }

    @ExceptionHandler(IdempotencyConflict.class)
    ResponseEntity<Map<String, Object>> idempotencyConflict(
            IdempotencyConflict error,
            HttpServletRequest request) {
        return error(
            HttpStatus.CONFLICT,
            "TD-API-CONFLICT-001",
            false,
            error,
            request
        );
    }

    @ExceptionHandler(StorageTicketExpired.class)
    ResponseEntity<Map<String, Object>> expired(
            StorageTicketExpired error,
            HttpServletRequest request) {
        return error(
            HttpStatus.CONFLICT,
            "TD-STORAGE-EXPIRED-001",
            true,
            error,
            request
        );
    }

    @ExceptionHandler(StorageIntegrityViolation.class)
    ResponseEntity<Map<String, Object>> integrity(
            StorageIntegrityViolation error,
            HttpServletRequest request) {
        return error(
            HttpStatus.UNPROCESSABLE_CONTENT,
            "TD-STORAGE-INTEGRITY-001",
            true,
            error,
            request
        );
    }

    @ExceptionHandler(DomainViolation.class)
    ResponseEntity<Map<String, Object>> conflict(
            DomainViolation error,
            HttpServletRequest request) {
        return error(
            HttpStatus.CONFLICT,
            "TD-API-CONFLICT-001",
            false,
            error,
            request
        );
    }

    private static ResponseEntity<Map<String, Object>> error(
            HttpStatus status,
            String code,
            boolean retryable,
            Exception error,
            HttpServletRequest request) {
        return ResponseEntity.status(status).body(StandardErrorFactory.body(
            request,
            code,
            error.getMessage(),
            retryable
        ));
    }
}
