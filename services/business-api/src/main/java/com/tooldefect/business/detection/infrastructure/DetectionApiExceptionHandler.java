package com.tooldefect.business.detection.infrastructure;

import java.util.Map;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

import com.tooldefect.business.detection.api.DetectionCallbackController;
import com.tooldefect.business.detection.api.DetectionQueryController;
import com.tooldefect.business.detection.domain.DetectionNotFound;
import com.tooldefect.business.shared.api.ContractValues;
import com.tooldefect.business.shared.api.StandardErrorFactory;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.domain.IdempotencyConflict;
import com.tooldefect.business.storage.domain.StorageIntegrityViolation;

@RestControllerAdvice(assignableTypes = {
    DetectionCallbackController.class,
    DetectionQueryController.class
})
public final class DetectionApiExceptionHandler {
    @ExceptionHandler({
        MissingRequestHeaderException.class,
        MethodArgumentTypeMismatchException.class,
        HttpMessageNotReadableException.class
    })
    ResponseEntity<Map<String, Object>> malformed(
            Exception error,
            HttpServletRequest request) {
        return response(
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
        return response(
            HttpStatus.UNPROCESSABLE_CONTENT,
            "TD-API-VALIDATION-001",
            false,
            error,
            request
        );
    }

    @ExceptionHandler(DetectionCallbackController.DetectionIdentityViolation.class)
    ResponseEntity<Map<String, Object>> denied(
            RuntimeException error,
            HttpServletRequest request) {
        return response(
            HttpStatus.FORBIDDEN,
            "TD-SECURITY-AUTHORIZATION-001",
            false,
            error,
            request
        );
    }

    @ExceptionHandler(DetectionQueryController.DetectionIdentityViolation.class)
    ResponseEntity<Map<String, Object>> deniedQuery(
            RuntimeException error,
            HttpServletRequest request) {
        return response(
            HttpStatus.FORBIDDEN,
            "TD-SECURITY-AUTHORIZATION-001",
            false,
            error,
            request
        );
    }

    @ExceptionHandler(DetectionNotFound.class)
    ResponseEntity<Map<String, Object>> notFound(
            DetectionNotFound error,
            HttpServletRequest request) {
        return response(
            HttpStatus.NOT_FOUND,
            "TD-API-NOT-FOUND-001",
            false,
            error,
            request
        );
    }

    @ExceptionHandler(IdempotencyConflict.class)
    ResponseEntity<Map<String, Object>> conflict(
            IdempotencyConflict error,
            HttpServletRequest request) {
        return response(
            HttpStatus.CONFLICT,
            "TD-API-CONFLICT-001",
            false,
            error,
            request
        );
    }

    @ExceptionHandler(StorageIntegrityViolation.class)
    ResponseEntity<Map<String, Object>> integrity(
            StorageIntegrityViolation error,
            HttpServletRequest request) {
        return response(
            HttpStatus.UNPROCESSABLE_CONTENT,
            "TD-STORAGE-INTEGRITY-001",
            false,
            error,
            request
        );
    }

    @ExceptionHandler(DomainViolation.class)
    ResponseEntity<Map<String, Object>> domain(
            DomainViolation error,
            HttpServletRequest request) {
        return response(
            HttpStatus.CONFLICT,
            "TD-API-CONFLICT-001",
            false,
            error,
            request
        );
    }

    private static ResponseEntity<Map<String, Object>> response(
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
