package com.tooldefect.business.quality.infrastructure;

import com.tooldefect.business.quality.api.QualityController;
import com.tooldefect.business.shared.api.ContractValues;
import com.tooldefect.business.shared.api.StandardErrorFactory;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.Map;

@RestControllerAdvice(assignableTypes = QualityController.class)
public final class QualityApiExceptionHandler {

    @ExceptionHandler(ContractValues.ContractInputViolation.class)
    ResponseEntity<Map<String, Object>> invalid(
            ContractValues.ContractInputViolation error,
            HttpServletRequest request) {
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_CONTENT).body(
            StandardErrorFactory.body(
                request, "TD-QUALITY-VALIDATION-001", error.getMessage(), false
            )
        );
    }
}
