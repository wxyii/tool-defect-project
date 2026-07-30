ALTER TABLE sys_user
    ALTER COLUMN external_subject DROP NOT NULL,
    ADD COLUMN username varchar(64),
    ADD COLUMN password_change_required boolean NOT NULL DEFAULT true;

CREATE UNIQUE INDEX uq_sys_user_normalized_username
    ON sys_user (lower(username))
    WHERE username IS NOT NULL;

UPDATE sys_user SET status = 'DISABLED';

CREATE TABLE sys_user_credential (
    user_id uuid PRIMARY KEY REFERENCES sys_user(user_id),
    password_hash varchar(512) NOT NULL,
    password_changed_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE auth_session (
    session_hash char(64) PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES sys_user(user_id),
    created_at timestamptz NOT NULL,
    last_accessed_at timestamptz NOT NULL,
    idle_expires_at timestamptz NOT NULL,
    absolute_expires_at timestamptz NOT NULL,
    source_address varchar(128),
    user_agent_digest char(64),
    revoked_at timestamptz,
    CHECK (idle_expires_at <= absolute_expires_at)
);

CREATE INDEX idx_auth_session_user_active
    ON auth_session(user_id, absolute_expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE auth_login_failure (
    normalized_username varchar(64) NOT NULL,
    source_address varchar(128) NOT NULL,
    window_started_at timestamptz NOT NULL,
    failure_count integer NOT NULL CHECK (failure_count > 0),
    blocked_until timestamptz,
    PRIMARY KEY (normalized_username, source_address)
);

INSERT INTO sys_role(role_id, role_code, role_name) VALUES
    ('10000000-0000-0000-0000-000000000001', 'OPERATOR', '操作员'),
    ('10000000-0000-0000-0000-000000000002', 'REVIEWER', '复核员'),
    ('10000000-0000-0000-0000-000000000003', 'QUALITY_MANAGER', '质量经理'),
    ('10000000-0000-0000-0000-000000000004', 'ALGORITHM_ENGINEER', '算法工程师'),
    ('10000000-0000-0000-0000-000000000005', 'MODEL_APPROVER', '模型审批员'),
    ('10000000-0000-0000-0000-000000000006', 'SYSTEM_OPERATOR', '系统管理员'),
    ('10000000-0000-0000-0000-000000000007', 'SECURITY_ADMIN', '安全管理员'),
    ('10000000-0000-0000-0000-000000000008', 'AUDITOR', '审计员')
ON CONFLICT (role_code) DO NOTHING;

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
FROM unnest(ARRAY[
    'capture:read', 'detection:read', 'image:view',
    'image:original:download', 'review:read', 'review:claim',
    'review:submit', 'review:annotate', 'review:escalate',
    'quality:override', 'dataset:approve', 'audit:read',
    'dataset:create', 'training:create', 'model:register',
    'model:validate', 'model:deploy:approve', 'model:rollback',
    'device:configure', 'user:manage', 'model:deploy:execute',
    'certificate:manage', 'security:policy:manage'
]) AS permission(code)
ON CONFLICT (permission_code) DO NOTHING;

INSERT INTO sys_role_permission(role_id, permission_id)
SELECT role.role_id, permission.permission_id
FROM sys_role role
JOIN (
    VALUES
        ('OPERATOR', 'capture:read'), ('OPERATOR', 'detection:read'),
        ('OPERATOR', 'image:view'),
        ('REVIEWER', 'capture:read'), ('REVIEWER', 'detection:read'),
        ('REVIEWER', 'image:view'), ('REVIEWER', 'review:read'),
        ('REVIEWER', 'review:claim'), ('REVIEWER', 'review:submit'),
        ('REVIEWER', 'review:annotate'),
        ('QUALITY_MANAGER', 'capture:read'),
        ('QUALITY_MANAGER', 'detection:read'),
        ('QUALITY_MANAGER', 'image:view'),
        ('QUALITY_MANAGER', 'image:original:download'),
        ('QUALITY_MANAGER', 'review:read'),
        ('QUALITY_MANAGER', 'review:claim'),
        ('QUALITY_MANAGER', 'review:submit'),
        ('QUALITY_MANAGER', 'review:annotate'),
        ('QUALITY_MANAGER', 'review:escalate'),
        ('QUALITY_MANAGER', 'quality:override'),
        ('QUALITY_MANAGER', 'dataset:approve'),
        ('QUALITY_MANAGER', 'audit:read'),
        ('ALGORITHM_ENGINEER', 'detection:read'),
        ('ALGORITHM_ENGINEER', 'image:view'),
        ('ALGORITHM_ENGINEER', 'dataset:create'),
        ('ALGORITHM_ENGINEER', 'training:create'),
        ('ALGORITHM_ENGINEER', 'model:register'),
        ('MODEL_APPROVER', 'detection:read'),
        ('MODEL_APPROVER', 'model:validate'),
        ('MODEL_APPROVER', 'model:deploy:approve'),
        ('MODEL_APPROVER', 'model:rollback'),
        ('SYSTEM_OPERATOR', 'capture:read'),
        ('SYSTEM_OPERATOR', 'detection:read'),
        ('SYSTEM_OPERATOR', 'image:view'),
        ('SYSTEM_OPERATOR', 'device:configure'),
        ('SYSTEM_OPERATOR', 'user:manage'),
        ('SYSTEM_OPERATOR', 'model:deploy:execute'),
        ('SYSTEM_OPERATOR', 'audit:read'),
        ('SECURITY_ADMIN', 'certificate:manage'),
        ('SECURITY_ADMIN', 'security:policy:manage'),
        ('SECURITY_ADMIN', 'audit:read'),
        ('AUDITOR', 'capture:read'), ('AUDITOR', 'detection:read'),
        ('AUDITOR', 'image:view'), ('AUDITOR', 'audit:read')
) AS mapping(role_code, permission_code)
    ON mapping.role_code = role.role_code
JOIN sys_permission permission
    ON permission.permission_code = mapping.permission_code
ON CONFLICT DO NOTHING;
