package com.tooldefect.business.model.infrastructure;

import com.tooldefect.business.model.api.ModelController;
import com.tooldefect.business.model.domain.ModelNotFound;
import com.tooldefect.business.shared.api.ContractValues;
import com.tooldefect.business.shared.api.StandardErrorFactory;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.shared.domain.IdempotencyConflict;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

import java.util.Map;

@RestControllerAdvice(assignableTypes = ModelController.class)
public final class ModelApiExceptionHandler {

    @ExceptionHandler({
        MissingRequestHeaderException.class,
        MethodArgumentTypeMismatchException.class,
        HttpMessageNotReadableException.class
    })
    ResponseEntity<Map<String, Object>> malformed(Exception error, HttpServletRequest request) {
        return response(HttpStatus.BAD_REQUEST, "TD-API-VALIDATION-001", false, error, request);
    }

    @ExceptionHandler(ContractValues.ContractInputViolation.class)
    ResponseEntity<Map<String, Object>> invalid(RuntimeException error, HttpServletRequest request) {
        return response(HttpStatus.UNPROCESSABLE_CONTENT, "TD-MODEL-VALIDATION-001", false, error, request);
    }

    @ExceptionHandler(ModelNotFound.class)
    ResponseEntity<Map<String, Object>> notFound(ModelNotFound error, HttpServletRequest request) {
        return response(HttpStatus.NOT_FOUND, "TD-MODEL-NOT-FOUND-001", false, error, request);
    }

    @ExceptionHandler(IdempotencyConflict.class)
    ResponseEntity<Map<String, Object>> conflict(IdempotencyConflict error, HttpServletRequest request) {
        return response(HttpStatus.CONFLICT, "TD-MODEL-CONFLICT-001", false, error, request);
    }

    @ExceptionHandler(DomainViolation.class)
    ResponseEntity<Map<String, Object>> domain(DomainViolation error, HttpServletRequest request) {
        return response(HttpStatus.CONFLICT, "TD-MODEL-CONFLICT-001", false, error, request);
    }

    private static ResponseEntity<Map<String, Object>> response(
            HttpStatus status, String code, boolean retryable,
            Exception error, HttpServletRequest request) {
        return ResponseEntity.status(status).body(
            StandardErrorFactory.body(request, code, error.getMessage(), retryable)
        );
    }
}
