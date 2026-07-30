package com.tooldefect.business.identity.infrastructure;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Set;

import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import com.tooldefect.business.shared.api.StandardErrorFactory;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import tools.jackson.databind.ObjectMapper;

@Component
public class LocalCsrfFilter extends OncePerRequestFilter {
    public static final String COOKIE = "TD-XSRF-TOKEN";
    public static final String HEADER = "X-TD-CSRF";
    private static final Set<String> SAFE = Set.of("GET", "HEAD", "OPTIONS");
    private static final SecureRandom RANDOM = new SecureRandom();

    private final ObjectMapper json;

    public LocalCsrfFilter(ObjectMapper json) {
        this.json = json;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain chain) throws ServletException, IOException {
        if (SAFE.contains(request.getMethod())) {
            chain.doFilter(request, response);
            return;
        }
        String cookie = LocalSessionAuthenticationFilter.cookie(request, COOKIE);
        String header = request.getHeader(HEADER);
        if (cookie == null || header == null
                || !MessageDigest.isEqual(
                    cookie.getBytes(StandardCharsets.UTF_8),
                    header.getBytes(StandardCharsets.UTF_8))) {
            StandardErrorFactory.write(
                request, response, json, 403,
                "TD-AUTH-CSRF-001", "请求来源校验失败", false);
            return;
        }
        chain.doFilter(request, response);
    }

    public static String issue(HttpServletResponse response, boolean secure) {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        response.addHeader(
            "Set-Cookie",
            ResponseCookie.from(COOKIE, token)
                .httpOnly(false)
                .secure(secure)
                .sameSite("Strict")
                .path("/")
                .build()
                .toString()
        );
        return token;
    }
}
