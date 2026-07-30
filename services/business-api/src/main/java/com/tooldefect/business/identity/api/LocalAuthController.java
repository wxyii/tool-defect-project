package com.tooldefect.business.identity.api;

import java.time.Duration;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseCookie;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.http.HttpStatus;

import com.tooldefect.business.identity.application.LocalIdentity;
import com.tooldefect.business.identity.application.LocalIdentityService;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import com.fasterxml.jackson.annotation.JsonProperty;

@RestController
@RequestMapping("/api/v1/auth")
public class LocalAuthController {
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final String SESSION_COOKIE = "TDSESSION";
    private static final String CSRF_COOKIE = "TD-XSRF-TOKEN";
    private static final String CSRF_HEADER = "X-TD-CSRF";
    private final LocalIdentityService identities;
    private final boolean secureCookie;

    public LocalAuthController(
            LocalIdentityService identities,
            @Value("${td.auth.secure-cookie:true}") boolean secureCookie) {
        this.identities = identities;
        this.secureCookie = secureCookie;
    }

    @GetMapping("/csrf")
    public Map<String, String> csrf(HttpServletResponse response) {
        return Map.of(
            "token", issueCsrf(response),
            "header_name", CSRF_HEADER
        );
    }

    @PostMapping("/login")
    public Map<String, Object> login(
            @RequestBody LoginRequest body,
            HttpServletRequest request,
            HttpServletResponse response) {
        LocalIdentity identity = identities.authenticate(
            body.username(), body.password(), request.getRemoteAddr());
        var session = identities.createSession(
            identity,
            request.getRemoteAddr(),
            request.getHeader("User-Agent")
        );
        response.addHeader(
            "Set-Cookie",
            ResponseCookie.from(
                    SESSION_COOKIE,
                    session.token())
                .httpOnly(true)
                .secure(secureCookie)
                .sameSite("Strict")
                .path("/")
                .maxAge(Duration.ofHours(8))
                .build()
                .toString()
        );
        return identity(identity);
    }

    @GetMapping("/session")
    public Map<String, Object> session(Authentication authentication) {
        return identity(requireIdentity(authentication));
    }

    @PostMapping("/logout")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void logout(
            Authentication authentication,
            HttpServletResponse response) {
        if (authentication != null
                && authentication.getCredentials() instanceof String token) {
            identities.revoke(token);
        }
        clearSessionCookie(response);
    }

    @PostMapping("/password/change")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void changePassword(
            Authentication authentication,
            @RequestBody PasswordChangeRequest body,
            HttpServletResponse response) {
        LocalIdentity identity = requireIdentity(authentication);
        identities.changePassword(
            identity.userId(), body.currentPassword(), body.newPassword());
        clearSessionCookie(response);
    }

    private void clearSessionCookie(HttpServletResponse response) {
        response.addHeader(
            "Set-Cookie",
            ResponseCookie.from(SESSION_COOKIE, "")
                .httpOnly(true)
                .secure(secureCookie)
                .sameSite("Strict")
                .path("/")
                .maxAge(Duration.ZERO)
                .build()
                .toString()
        );
    }

    private String issueCsrf(HttpServletResponse response) {
        byte[] bytes = new byte[32];
        RANDOM.nextBytes(bytes);
        String token = Base64.getUrlEncoder().withoutPadding()
            .encodeToString(bytes);
        response.addHeader(
            "Set-Cookie",
            ResponseCookie.from(CSRF_COOKIE, token)
                .httpOnly(false)
                .secure(secureCookie)
                .sameSite("Strict")
                .path("/")
                .build()
                .toString()
        );
        return token;
    }

    static LocalIdentity requireIdentity(Authentication authentication) {
        if (authentication == null
                || !(authentication.getPrincipal() instanceof LocalIdentity identity)) {
            throw new org.springframework.security.authentication
                .InsufficientAuthenticationException("身份认证失败");
        }
        return identity;
    }

    static Map<String, Object> identity(LocalIdentity identity) {
        return Map.of(
            "user_id", identity.userId().toString(),
            "username", identity.username(),
            "display_name", identity.displayName(),
            "roles", identity.roles(),
            "permissions", identity.permissions(),
            "password_change_required", identity.passwordChangeRequired()
        );
    }

    public record LoginRequest(String username, String password) {
    }

    public record PasswordChangeRequest(
            @JsonProperty("current_password") String currentPassword,
            @JsonProperty("new_password") String newPassword) {
    }
}
