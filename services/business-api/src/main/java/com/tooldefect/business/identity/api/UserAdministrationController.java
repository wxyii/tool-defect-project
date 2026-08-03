package com.tooldefect.business.identity.api;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.http.HttpStatus;

import com.tooldefect.business.identity.application.LocalIdentity;
import com.tooldefect.business.identity.application.LocalIdentityService;
import com.fasterxml.jackson.annotation.JsonProperty;

@RestController
@RequestMapping("/api/v1/users")
public class UserAdministrationController {
    private final LocalIdentityService identities;

    public UserAdministrationController(LocalIdentityService identities) {
        this.identities = identities;
    }

    @GetMapping
    public Map<String, Object> list() {
        return Map.of("items", identities.listUsers());
    }

    @GetMapping("/role-migration-preview")
    public Map<String, Object> roleMigrationPreview() {
        return Map.of("items", identities.previewRoleMappings());
    }

    @PostMapping
    public Map<String, String> create(
            Authentication authentication,
            @RequestBody CreateUserRequest body) {
        UUID id = identities.createUser(
            body.username(), body.displayName(), body.initialPassword(),
            body.roles(), actor(authentication));
        return Map.of("user_id", id.toString());
    }

    @PatchMapping("/{userId}/status")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void status(
            Authentication authentication,
            @org.springframework.web.bind.annotation.PathVariable UUID userId,
            @RequestBody StatusRequest body) {
        identities.setStatus(userId, body.status(), actor(authentication));
    }

    @PutMapping("/{userId}/roles")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void roles(
            Authentication authentication,
            @org.springframework.web.bind.annotation.PathVariable UUID userId,
            @RequestBody RolesRequest body) {
        identities.setRoles(userId, body.roles(), actor(authentication));
    }

    @PostMapping("/{userId}/role-migration")
    public Map<String, Object> confirmRoleMigration(
            Authentication authentication,
            @org.springframework.web.bind.annotation.PathVariable UUID userId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @RequestBody RoleMigrationRequest body) {
        return identities.confirmRoleMigration(
            userId, body.role(), actor(authentication), body.reason());
    }

    @PatchMapping("/{userId}/display-name")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void displayName(
            Authentication authentication,
            @org.springframework.web.bind.annotation.PathVariable UUID userId,
            @RequestBody DisplayNameRequest body) {
        identities.setDisplayName(userId, body.displayName(), actor(authentication));
    }

    @PostMapping("/{userId}/password-reset")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void reset(
            Authentication authentication,
            @org.springframework.web.bind.annotation.PathVariable UUID userId,
            @RequestBody PasswordResetRequest body) {
        identities.resetPassword(
            userId, body.temporaryPassword(), actor(authentication));
    }

    static String actor(Authentication authentication) {
        if (authentication != null
                && authentication.getPrincipal() instanceof LocalIdentity identity) {
            return identity.userId().toString();
        }
        return authentication == null ? "unknown" : authentication.getName();
    }

    public record CreateUserRequest(
            String username,
            @JsonProperty("display_name") String displayName,
            @JsonProperty("initial_password") String initialPassword,
            List<String> roles) {
    }

    public record StatusRequest(String status) {
    }

    public record DisplayNameRequest(
            @JsonProperty("display_name") String displayName) {
    }

    public record RolesRequest(List<String> roles) {
    }

    public record RoleMigrationRequest(
            String role,
            String reason) {
    }

    public record PasswordResetRequest(
            @JsonProperty("temporary_password") String temporaryPassword) {
    }
}
