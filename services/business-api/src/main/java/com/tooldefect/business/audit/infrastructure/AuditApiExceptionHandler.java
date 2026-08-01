package com.tooldefect.business.audit.infrastructure;

import java.util.Map;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import com.tooldefect.business.audit.api.AuditController;
import com.tooldefect.business.shared.api.ContractValues;
import com.tooldefect.business.shared.api.StandardErrorFactory;

@RestControllerAdvice(assignableTypes = AuditController.class)
public final class AuditApiExceptionHandler {
    @ExceptionHandler(ContractValues.ContractInputViolation.class)
    ResponseEntity<Map<String, Object>> invalid(
            ContractValues.ContractInputViolation error,
            HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_CONTENT).body(
            StandardErrorFactory.body(
                request,
                "TD-AUDIT-VALIDATION-001",
                error.getMessage(),
                false
            )
        );
    }
}
