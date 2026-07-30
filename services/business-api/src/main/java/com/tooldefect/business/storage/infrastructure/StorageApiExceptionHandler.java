package com.tooldefect.business.storage.infrastructure;

import java.util.Map;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.http.converter.HttpMessageNotReadableException;

import com.tooldefect.business.shared.api.StandardErrorFactory;
import com.tooldefect.business.shared.domain.DomainViolation;
import com.tooldefect.business.storage.api.StorageTicketController;
import com.tooldefect.business.storage.api.ImageAccessController;
import com.tooldefect.business.storage.domain.StorageAccessDenied;
import com.tooldefect.business.storage.domain.StorageIntegrityViolation;
import com.tooldefect.business.storage.domain.StorageTicketExpired;

@RestControllerAdvice(assignableTypes = {
    StorageTicketController.class,
    ImageAccessController.class
})
public final class StorageApiExceptionHandler {
    @ExceptionHandler({
        MissingRequestHeaderException.class,
        MethodArgumentTypeMismatchException.class,
        HttpMessageNotReadableException.class
    })
    ResponseEntity<Map<String, Object>> malformedRequest(
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

    @ExceptionHandler(StorageTicketController.ContractInputViolation.class)
    ResponseEntity<Map<String, Object>> invalidContractInput(
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

    @ExceptionHandler(ImageAccessController.ContractInputViolation.class)
    ResponseEntity<Map<String, Object>> invalidImageAccess(
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

    @ExceptionHandler(StorageTicketController.StorageIdentityViolation.class)
    ResponseEntity<Map<String, Object>> missingDeviceScope(
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

    @ExceptionHandler(ImageAccessController.StorageIdentityViolation.class)
    ResponseEntity<Map<String, Object>> missingUserIdentity(
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

    @ExceptionHandler(StorageAccessDenied.class)
    ResponseEntity<Map<String, Object>> denied(
            StorageAccessDenied error,
            HttpServletRequest request) {
        return error(
            HttpStatus.FORBIDDEN,
            "TD-SECURITY-AUTHORIZATION-001",
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
