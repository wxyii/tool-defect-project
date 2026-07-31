package com.tooldefect.business.dataset.infrastructure;

import com.tooldefect.business.dataset.api.DatasetController;
import com.tooldefect.business.dataset.domain.DatasetNotFound;
import com.tooldefect.business.shared.api.StandardErrorFactory;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.domain.IdempotencyConflict;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.Map;

@RestControllerAdvice(assignableTypes = DatasetController.class)
public final class DatasetApiExceptionHandler {

    @ExceptionHandler({MissingRequestHeaderException.class, org.springframework.http.converter.HttpMessageNotReadableException.class})
    ResponseEntity<Map<String, Object>> malformed(Exception error, HttpServletRequest request) {
        return response(HttpStatus.BAD_REQUEST, "TD-API-VALIDATION-001", false, error, request);
    }

    @ExceptionHandler(com.tooldefect.business.shared.api.ContractValues.ContractInputViolation.class)
    ResponseEntity<Map<String, Object>> invalid(RuntimeException error, HttpServletRequest request) {
        return response(HttpStatus.UNPROCESSABLE_CONTENT, "TD-API-VALIDATION-001", false, error, request);
    }

    @ExceptionHandler(DatasetNotFound.class)
    ResponseEntity<Map<String, Object>> notFound(DatasetNotFound error, HttpServletRequest request) {
        return response(HttpStatus.NOT_FOUND, "TD-API-NOT-FOUND-001", false, error, request);
    }

    @ExceptionHandler(IdempotencyConflict.class)
    ResponseEntity<Map<String, Object>> conflict(IdempotencyConflict error, HttpServletRequest request) {
        return response(HttpStatus.CONFLICT, "TD-API-CONFLICT-001", false, error, request);
    }

    @ExceptionHandler(DomainViolation.class)
    ResponseEntity<Map<String, Object>> domain(DomainViolation error, HttpServletRequest request) {
        return response(HttpStatus.CONFLICT, "TD-API-CONFLICT-001", false, error, request);
    }

    private static ResponseEntity<Map<String, Object>> response(HttpStatus status, String code, boolean retryable, Exception error, HttpServletRequest request) {
        return ResponseEntity.status(status).body(StandardErrorFactory.body(request, code, error.getMessage(), retryable));
    }
}
