package com.tooldefect.business.identity.domain;

import java.util.EnumMap;
import java.util.Map;
import java.util.Set;

/** 首期职责分离基线；数据库角色绑定只能在此基线上进一步收紧。 */
public final class RolePermissionMatrix {
    private static final Map<SystemRole, Set<String>> PERMISSIONS =
        permissions();

    private RolePermissionMatrix() {
    }

    public static boolean allows(SystemRole role, String permission) {
        return PERMISSIONS.getOrDefault(role, Set.of()).contains(permission);
    }

    public static Set<String> permissions(SystemRole role) {
        return PERMISSIONS.getOrDefault(role, Set.of());
    }

    private static Map<SystemRole, Set<String>> permissions() {
        Map<SystemRole, Set<String>> values =
            new EnumMap<>(SystemRole.class);
        values.put(
            SystemRole.OPERATOR,
            Set.of("capture:read", "detection:read", "image:view")
        );
        values.put(
            SystemRole.REVIEWER,
            Set.of(
                "capture:read",
                "detection:read",
                "image:view",
                "review:read",
                "review:claim",
                "review:submit",
                "review:annotate"
            )
        );
        values.put(
            SystemRole.QUALITY_MANAGER,
            Set.of(
                "capture:read",
                "detection:read",
                "image:view",
                "image:original:download",
                "review:read",
                "review:claim",
                "review:submit",
                "review:annotate",
                "review:escalate",
                "quality:override",
                "quality:read",
                "dataset:approve",
                "audit:read"
            )
        );
        values.put(
            SystemRole.ALGORITHM_ENGINEER,
            Set.of(
                "detection:read",
                "image:view",
                "dataset:create",
                "training:create",
                "training:read",
                "model:register"
            )
        );
        values.put(
            SystemRole.MODEL_APPROVER,
            Set.of(
                "detection:read",
                "model:validate",
                "model:deploy:approve",
                "model:rollback",
                "training:read"
            )
        );
        values.put(
            SystemRole.SYSTEM_OPERATOR,
            Set.of(
                "capture:read",
                "detection:read",
                "image:view",
                "device:configure",
                "user:manage",
                "model:deploy:execute",
                "audit:read"
            )
        );
        values.put(
            SystemRole.SECURITY_ADMIN,
            Set.of(
                "certificate:manage",
                "security:policy:manage",
                "audit:read"
            )
        );
        values.put(
            SystemRole.AUDITOR,
            Set.of(
                "capture:read",
                "detection:read",
                "image:view",
                "audit:read",
                "quality:read",
                "training:read"
            )
        );
        return Map.copyOf(values);
    }
}
