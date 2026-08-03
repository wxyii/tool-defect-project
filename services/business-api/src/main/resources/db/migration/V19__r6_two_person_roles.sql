-- R6：人员业务角色收敛为生产员工和管理员。
-- 旧角色及其历史绑定保留为只读迁移证据；第二版会话只读取已确认的 person_role。

ALTER TABLE sys_user
    ADD COLUMN person_role varchar(32),
    ADD CONSTRAINT ck_sys_user_person_role
    CHECK (person_role IS NULL OR person_role IN (
        'PRODUCTION_EMPLOYEE', 'ADMINISTRATOR'
    ));

CREATE TABLE sys_user_role_migration_v2 (
    migration_id uuid PRIMARY KEY,
    user_id uuid NOT NULL UNIQUE REFERENCES sys_user(user_id),
    legacy_roles varchar(64)[] NOT NULL DEFAULT ARRAY[]::varchar(64)[],
    suggested_role varchar(32)
        CHECK (suggested_role IS NULL OR suggested_role IN (
            'PRODUCTION_EMPLOYEE', 'ADMINISTRATOR'
        )),
    selected_role varchar(32)
        CHECK (selected_role IS NULL OR selected_role IN (
            'PRODUCTION_EMPLOYEE', 'ADMINISTRATOR'
        )),
    status varchar(24) NOT NULL CHECK (
        status IN ('UNCONFIRMED', 'CONFIRMED', 'CONFLICT', 'REJECTED')
    ),
    decision_reason varchar(1024),
    decided_by uuid REFERENCES sys_user(user_id),
    decided_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    CONSTRAINT ck_sys_user_role_migration_decision CHECK (
        (status = 'CONFIRMED' AND selected_role IS NOT NULL
            AND decided_by IS NOT NULL AND decided_at IS NOT NULL)
        OR (status <> 'CONFIRMED' AND selected_role IS NULL)
    )
);

CREATE INDEX idx_sys_user_role_migration_status
    ON sys_user_role_migration_v2(status, user_id);

INSERT INTO sys_user_role_migration_v2(
    migration_id, user_id, legacy_roles, suggested_role, status
)
SELECT
    gen_random_uuid(),
    u.user_id,
    COALESCE(
        array_agg(r.role_code ORDER BY r.role_code)
            FILTER (WHERE r.role_code IS NOT NULL),
        ARRAY[]::varchar(64)[]
    ),
    CASE
        WHEN count(r.role_code) = 1 AND min(r.role_code) = 'OPERATOR'
            THEN 'PRODUCTION_EMPLOYEE'
        ELSE NULL
    END,
    CASE
        WHEN count(r.role_code) = 0
            THEN 'UNCONFIRMED'
        WHEN count(r.role_code) = 1 AND min(r.role_code) = 'OPERATOR'
            THEN 'UNCONFIRMED'
        ELSE 'CONFLICT'
    END
FROM sys_user u
LEFT JOIN sys_user_role ur ON ur.user_id = u.user_id
LEFT JOIN sys_role r ON r.role_id = ur.role_id
GROUP BY u.user_id
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO sys_role(role_id, role_code, role_name) VALUES
    ('10000000-0000-0000-0000-000000000009', 'PRODUCTION_EMPLOYEE', '生产员工'),
    ('10000000-0000-0000-0000-00000000000a', 'ADMINISTRATOR', '管理员')
ON CONFLICT (role_code) DO NOTHING;

-- 取消人员可见的数据集版本和训练能力；旧权限行保留用于历史审计查询，
-- 但不再绑定到任何人员业务角色。
DELETE FROM sys_role_permission mapping
USING sys_permission permission
WHERE mapping.permission_id = permission.permission_id
  AND permission.permission_code IN (
      'dataset:create', 'dataset:approve', 'training:create', 'training:read'
  );

-- 旧角色仅作为迁移快照保留，不再为第二版人员会话提供原子权限。
DELETE FROM sys_role_permission mapping
USING sys_role role
WHERE mapping.role_id = role.role_id
  AND role.role_code NOT IN ('PRODUCTION_EMPLOYEE', 'ADMINISTRATOR');

INSERT INTO sys_role_permission(role_id, permission_id)
SELECT role.role_id, permission.permission_id
FROM sys_role role
JOIN sys_permission permission
  ON permission.permission_code IN (
      'capture:read', 'detection:read', 'image:view',
      'manual-detection:read', 'manual-detection:write'
  )
WHERE role.role_code = 'PRODUCTION_EMPLOYEE'
ON CONFLICT DO NOTHING;

INSERT INTO sys_role_permission(role_id, permission_id)
SELECT role.role_id, permission.permission_id
FROM sys_role role
JOIN sys_permission permission
  ON permission.permission_code IN (
      'capture:read', 'detection:read', 'image:view',
      'image:original:download', 'review:read', 'review:claim',
      'review:submit', 'review:annotate', 'review:escalate',
      'quality:override', 'quality:read', 'model:register',
      'model:validate', 'model:approve', 'model:deploy:approve',
      'model:rollback', 'device:configure', 'user:manage',
      'model:deploy:execute', 'certificate:manage',
      'security:policy:manage', 'manual-detection:read',
      'manual-detection:read:all', 'manual-detection:write', 'audit:read'
  )
WHERE role.role_code = 'ADMINISTRATOR'
ON CONFLICT DO NOTHING;

COMMENT ON COLUMN sys_user.person_role IS
    'R6 已确认的人员业务角色；为空表示未完成迁移，不授予第二版人员原子权限';

COMMENT ON TABLE sys_user_role_migration_v2 IS
    'R6 旧角色映射预览和逐账号确认事实；旧角色快照只读保留';
