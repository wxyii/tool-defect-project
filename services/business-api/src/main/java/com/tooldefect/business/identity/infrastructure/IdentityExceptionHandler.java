package com.tooldefect.business.identity.infrastructure;

import java.io.IOException;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.InsufficientAuthenticationException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import com.tooldefect.business.shared.api.StandardErrorFactory;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import tools.jackson.databind.ObjectMapper;

@RestControllerAdvice
public class IdentityExceptionHandler {
    private final ObjectMapper json;

    public IdentityExceptionHandler(ObjectMapper json) {
        this.json = json;
    }

    @ExceptionHandler({
        BadCredentialsException.class,
        InsufficientAuthenticationException.class
    })
    public void unauthorized(
            HttpServletRequest request,
            HttpServletResponse response) throws IOException {
        StandardErrorFactory.write(
            request, response, json, 401,
            "TD-AUTH-UNAUTHORIZED-001", "身份认证失败", false);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public void invalid(
            HttpServletRequest request,
            HttpServletResponse response,
            IllegalArgumentException failure) throws IOException {
        StandardErrorFactory.write(
            request, response, json, 422,
            "TD-AUTH-VALIDATION-001", failure.getMessage(), false);
    }

    @ExceptionHandler(DataIntegrityViolationException.class)
    public void conflict(
            HttpServletRequest request,
            HttpServletResponse response) throws IOException {
        StandardErrorFactory.write(
            request, response, json, 409,
            "TD-AUTH-CONFLICT-001", "账号或角色状态冲突", false);
    }
}
