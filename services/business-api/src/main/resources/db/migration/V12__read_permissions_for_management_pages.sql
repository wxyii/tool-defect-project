-- 补齐角色矩阵已声明、但 V7 初始权限数据遗漏的只读权限。
-- 数据集和模型页面继续复用后端既有的动作权限与 audit:read，避免引入
-- 与接口鉴权规则不一致的平行权限名。

INSERT INTO sys_permission(permission_id, permission_code, description)
SELECT (
        substr(md5('tool-defect-permission:' || code), 1, 8) || '-' ||
        substr(md5('tool-defect-permission:' || code), 9, 4) || '-4' ||
        substr(md5('tool-defect-permission:' || code), 14, 3) || '-8' ||
        substr(md5('tool-defect-permission:' || code), 18, 3) || '-' ||
        substr(md5('tool-defect-permission:' || code), 21, 12)
    )::uuid,
    code,
    '系统权限：' || code
FROM unnest(ARRAY['training:read', 'quality:read']) AS permission(code)
ON CONFLICT (permission_code) DO NOTHING;

INSERT INTO sys_role_permission(role_id, permission_id)
SELECT role.role_id, permission.permission_id
FROM sys_role role
JOIN (
    VALUES
        ('QUALITY_MANAGER', 'quality:read'),
        ('ALGORITHM_ENGINEER', 'training:read'),
        ('MODEL_APPROVER', 'training:read'),
        ('AUDITOR', 'quality:read'),
        ('AUDITOR', 'training:read')
) AS mapping(role_code, permission_code)
    ON mapping.role_code = role.role_code
JOIN sys_permission permission
    ON permission.permission_code = mapping.permission_code
ON CONFLICT DO NOTHING;
