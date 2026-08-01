package com.tooldefect.business.identity.application;

import java.security.Principal;
import java.util.List;
import java.util.UUID;

/** 本地人员身份；认证名称固定为用户 UUID，供审计和业务外键复用。 */
public record LocalIdentity(
        UUID userId,
        String username,
        String displayName,
        String status,
        boolean passwordChangeRequired,
        List<String> roles,
        List<String> permissions) implements Principal {
    @Override
    public String getName() {
        return userId.toString();
    }
}
