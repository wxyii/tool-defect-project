package com.tooldefect.business.identity.domain;

import java.util.EnumMap;
import java.util.Map;
import java.util.Set;

/** 第二版人员业务角色基线；设备和服务身份不使用此矩阵。 */
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
            SystemRole.PRODUCTION_EMPLOYEE,
            Set.of(
                "capture:read",
                "detection:read",
                "image:view",
                "manual-detection:read",
                "manual-detection:write"
            )
        );
        values.put(
            SystemRole.ADMINISTRATOR,
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
                "model:register",
                "model:validate",
                "model:approve",
                "model:deploy:approve",
                "model:rollback",
                "device:configure",
                "user:manage",
                "model:deploy:execute",
                "certificate:manage",
                "security:policy:manage",
                "manual-detection:read",
                "manual-detection:read:all",
                "manual-detection:write",
                "audit:read",
                "sample:read",
                "sample:feedback",
                "sample:candidate:write",
                "sample:export",
                "sample:export:download",
                "sample:external-receipt"
            )
        );
        return Map.copyOf(values);
    }
}
