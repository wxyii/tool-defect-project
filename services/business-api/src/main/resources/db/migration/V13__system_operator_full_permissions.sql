-- 系统管理员作为最高权限角色，获得当前全部人员业务权限。
-- 该授权不改变内部服务作用域、资源状态校验、不可篡改约束、审批记录
-- 或双人审批规则；新权限加入后需同步角色权限基线和迁移。

INSERT INTO sys_role_permission(role_id, permission_id)
SELECT role.role_id, permission.permission_id
FROM sys_role role
CROSS JOIN sys_permission permission
WHERE role.role_code = 'SYSTEM_OPERATOR'
ON CONFLICT DO NOTHING;
