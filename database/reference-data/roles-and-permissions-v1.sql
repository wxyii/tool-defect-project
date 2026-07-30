-- 仅保存稳定代码，不保存用户或凭据；标识由部署导入器生成。
INSERT INTO sys_role(role_id, role_code, role_name)
VALUES
    ('00000000-0000-7000-8000-000000000001', 'OPERATOR', '工位操作员'),
    ('00000000-0000-7000-8000-000000000002', 'REVIEWER', '质量复核员'),
    ('00000000-0000-7000-8000-000000000003', 'QUALITY_MANAGER', '质量负责人'),
    ('00000000-0000-7000-8000-000000000004', 'ALGORITHM_ENGINEER', '算法工程师'),
    ('00000000-0000-7000-8000-000000000005', 'MODEL_APPROVER', '模型审批人'),
    ('00000000-0000-7000-8000-000000000006', 'SYSTEM_OPERATOR', '系统运维'),
    ('00000000-0000-7000-8000-000000000007', 'AUDITOR', '审计员'),
    ('00000000-0000-7000-8000-000000000008', 'SECURITY_ADMIN', '安全管理员')
ON CONFLICT (role_code) DO NOTHING;

INSERT INTO sys_permission(permission_id, permission_code, description)
VALUES
    ('00000000-0000-7000-8000-000000000101', 'detection:read', '查看授权范围检测'),
    ('00000000-0000-7000-8000-000000000102', 'review:submit', '提交人工复核'),
    ('00000000-0000-7000-8000-000000000103', 'image:original:download', '下载授权原图'),
    ('00000000-0000-7000-8000-000000000104', 'model:register', '登记候选模型'),
    ('00000000-0000-7000-8000-000000000105', 'model:approve', '独立审批模型部署'),
    ('00000000-0000-7000-8000-000000000106', 'operation:dead-letter', '处置死信'),
    ('00000000-0000-7000-8000-000000000107', 'audit:read', '查看审计记录'),
    ('00000000-0000-7000-8000-000000000108', 'capture:read', '读取授权范围采集'),
    ('00000000-0000-7000-8000-000000000109', 'capture:write', '写入本工位采集'),
    ('00000000-0000-7000-8000-000000000110', 'dataset:create', '创建数据集草稿'),
    ('00000000-0000-7000-8000-000000000111', 'dataset:read', '读取授权数据集'),
    ('00000000-0000-7000-8000-000000000112', 'detection:retry', '申请授权检测重试'),
    ('00000000-0000-7000-8000-000000000113', 'device:heartbeat', '上报本设备心跳'),
    ('00000000-0000-7000-8000-000000000114', 'event:read', '读取授权实时事件'),
    ('00000000-0000-7000-8000-000000000115', 'image:view', '查看授权图片'),
    ('00000000-0000-7000-8000-000000000116', 'inference:callback', '提交推理内部回调'),
    ('00000000-0000-7000-8000-000000000117', 'model:deploy', '执行批准的模型部署'),
    ('00000000-0000-7000-8000-000000000118', 'model:rollback', '回滚生产模型'),
    ('00000000-0000-7000-8000-000000000119', 'model:validate', '提交模型验证结论'),
    ('00000000-0000-7000-8000-000000000120', 'review:annotate', '上传复核标注'),
    ('00000000-0000-7000-8000-000000000121', 'review:claim', '认领授权复核任务'),
    ('00000000-0000-7000-8000-000000000122', 'review:read', '读取授权复核任务'),
    ('00000000-0000-7000-8000-000000000123', 'runtime:read', '读取内部运行状态'),
    ('00000000-0000-7000-8000-000000000124', 'training:create', '创建训练运行'),
    ('00000000-0000-7000-8000-000000000125', 'training:read', '读取训练运行'),
    ('00000000-0000-7000-8000-000000000126', 'quality:override', '覆盖最终质量处置'),
    ('00000000-0000-7000-8000-000000000127', 'dataset:approve', '批准冻结数据集'),
    ('00000000-0000-7000-8000-000000000128', 'device:configure', '配置授权设备'),
    ('00000000-0000-7000-8000-000000000129', 'user:manage', '管理用户角色与范围')
ON CONFLICT (permission_code) DO NOTHING;

WITH grant_matrix(role_code, permission_code) AS (
    VALUES
        ('OPERATOR', 'capture:read'),
        ('OPERATOR', 'capture:write'),
        ('OPERATOR', 'device:heartbeat'),
        ('OPERATOR', 'detection:read'),
        ('OPERATOR', 'image:view'),
        ('REVIEWER', 'detection:read'),
        ('REVIEWER', 'image:view'),
        ('REVIEWER', 'review:read'),
        ('REVIEWER', 'review:claim'),
        ('REVIEWER', 'review:submit'),
        ('REVIEWER', 'review:annotate'),
        ('QUALITY_MANAGER', 'detection:read'),
        ('QUALITY_MANAGER', 'detection:retry'),
        ('QUALITY_MANAGER', 'image:view'),
        ('QUALITY_MANAGER', 'review:read'),
        ('QUALITY_MANAGER', 'review:claim'),
        ('QUALITY_MANAGER', 'review:submit'),
        ('QUALITY_MANAGER', 'quality:override'),
        ('QUALITY_MANAGER', 'dataset:approve'),
        ('ALGORITHM_ENGINEER', 'detection:read'),
        ('ALGORITHM_ENGINEER', 'image:view'),
        ('ALGORITHM_ENGINEER', 'dataset:create'),
        ('ALGORITHM_ENGINEER', 'dataset:read'),
        ('ALGORITHM_ENGINEER', 'training:create'),
        ('ALGORITHM_ENGINEER', 'training:read'),
        ('ALGORITHM_ENGINEER', 'model:register'),
        ('ALGORITHM_ENGINEER', 'model:validate'),
        ('MODEL_APPROVER', 'model:validate'),
        ('MODEL_APPROVER', 'model:approve'),
        ('MODEL_APPROVER', 'model:deploy'),
        ('MODEL_APPROVER', 'model:rollback'),
        ('SYSTEM_OPERATOR', 'device:configure'),
        ('SYSTEM_OPERATOR', 'user:manage'),
        ('SYSTEM_OPERATOR', 'operation:dead-letter'),
        ('SYSTEM_OPERATOR', 'event:read'),
        ('SYSTEM_OPERATOR', 'runtime:read'),
        ('SYSTEM_OPERATOR', 'detection:retry'),
        ('SYSTEM_OPERATOR', 'audit:read'),
        ('SECURITY_ADMIN', 'user:manage'),
        ('SECURITY_ADMIN', 'operation:dead-letter'),
        ('SECURITY_ADMIN', 'audit:read'),
        ('AUDITOR', 'audit:read'),
        ('AUDITOR', 'detection:read')
)
INSERT INTO sys_role_permission(role_id, permission_id)
SELECT role.role_id, permission.permission_id
FROM grant_matrix grant_item
JOIN sys_role role
    ON role.role_code = grant_item.role_code
JOIN sys_permission permission
    ON permission.permission_code = grant_item.permission_code
ON CONFLICT (role_id, permission_id) DO NOTHING;
