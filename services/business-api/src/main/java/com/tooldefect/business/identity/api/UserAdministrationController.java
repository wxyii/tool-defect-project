package com.tooldefect.business.identity.api;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.http.HttpStatus;

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

    @PostMapping
    public Map<String, String> create(
            Authentication authentication,
            @RequestBody CreateUserRequest body) {
        UUID id = identities.createUser(
            body.username(), body.displayName(), body.initialPassword(),
            body.roles(), authentication.getName());
        return Map.of("user_id", id.toString());
    }

    @PatchMapping("/{userId}/status")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void status(
            Authentication authentication,
            @org.springframework.web.bind.annotation.PathVariable UUID userId,
            @RequestBody StatusRequest body) {
        identities.setStatus(userId, body.status(), authentication.getName());
    }

    @PutMapping("/{userId}/roles")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void roles(
            Authentication authentication,
            @org.springframework.web.bind.annotation.PathVariable UUID userId,
            @RequestBody RolesRequest body) {
        identities.setRoles(userId, body.roles(), authentication.getName());
    }

    @PostMapping("/{userId}/password-reset")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void reset(
            Authentication authentication,
            @org.springframework.web.bind.annotation.PathVariable UUID userId,
            @RequestBody PasswordResetRequest body) {
        identities.resetPassword(
            userId, body.temporaryPassword(), authentication.getName());
    }

    public record CreateUserRequest(
            String username,
            @JsonProperty("display_name") String displayName,
            @JsonProperty("initial_password") String initialPassword,
            List<String> roles) {
    }

    public record StatusRequest(String status) {
    }

    public record RolesRequest(List<String> roles) {
    }

    public record PasswordResetRequest(
            @JsonProperty("temporary_password") String temporaryPassword) {
    }
}
