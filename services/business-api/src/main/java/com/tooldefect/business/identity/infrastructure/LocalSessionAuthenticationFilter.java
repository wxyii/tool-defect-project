package com.tooldefect.business.identity.infrastructure;

import java.io.IOException;
import java.util.Arrays;

import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import com.tooldefect.business.identity.application.LocalIdentity;
import com.tooldefect.business.identity.application.LocalIdentityService;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

@Component
public class LocalSessionAuthenticationFilter extends OncePerRequestFilter {
    public static final String SESSION_COOKIE = "TDSESSION";
    private final LocalIdentityService identities;

    public LocalSessionAuthenticationFilter(LocalIdentityService identities) {
        this.identities = identities;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain chain) throws ServletException, IOException {
        String token = cookie(request, SESSION_COOKIE);
        LocalIdentity identity = identities.resolveSession(token);
        if (identity != null) {
            var authorities = identity.permissions().stream()
                .map(SimpleGrantedAuthority::new)
                .toList();
            var authentication = UsernamePasswordAuthenticationToken.authenticated(
                identity,
                token,
                authorities
            );
            SecurityContextHolder.getContext().setAuthentication(authentication);
        }
        try {
            chain.doFilter(request, response);
        } finally {
            SecurityContextHolder.clearContext();
        }
    }

    public static String cookie(HttpServletRequest request, String name) {
        if (request.getCookies() == null) {
            return null;
        }
        return Arrays.stream(request.getCookies())
            .filter(cookie -> name.equals(cookie.getName()))
            .map(Cookie::getValue)
            .findFirst()
            .orElse(null);
    }
}
