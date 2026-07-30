package com.tooldefect.business.identity.infrastructure;

import java.io.IOException;

import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import com.tooldefect.business.identity.application.LocalIdentity;
import com.tooldefect.business.shared.api.StandardErrorFactory;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import tools.jackson.databind.ObjectMapper;

@Component
public class PasswordChangeRequiredFilter extends OncePerRequestFilter {
    private final ObjectMapper json;

    public PasswordChangeRequiredFilter(ObjectMapper json) {
        this.json = json;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain chain) throws ServletException, IOException {
        var authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null
                && authentication.getPrincipal() instanceof LocalIdentity identity
                && identity.passwordChangeRequired()
                && !request.getRequestURI().startsWith("/api/v1/auth/")) {
            StandardErrorFactory.write(
                request, response, json, 403,
                "TD-AUTH-PASSWORD-CHANGE-REQUIRED-001",
                "必须先修改初始密码", false);
            return;
        }
        chain.doFilter(request, response);
    }
}
