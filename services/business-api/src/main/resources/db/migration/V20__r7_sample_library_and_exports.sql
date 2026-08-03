-- R7：管理员反馈、待整理样本候选、异步导出和下载审计。
-- 只追加事实；候选/导出状态是受约束的可重建投影，图片和压缩包只保存在对象存储。

ALTER TABLE admin_feedback_v2
    ADD COLUMN supersedes_feedback_id uuid,
    ADD COLUMN revision_no integer NOT NULL DEFAULT 1
        CHECK (revision_no >= 1),
    ADD CONSTRAINT fk_admin_feedback_supersedes
        FOREIGN KEY (supersedes_feedback_id)
        REFERENCES admin_feedback_v2(feedback_id),
    ADD CONSTRAINT ck_admin_feedback_not_self
        CHECK (
            supersedes_feedback_id IS NULL
            OR supersedes_feedback_id <> feedback_id
        );

CREATE INDEX idx_admin_feedback_item_revision
    ON admin_feedback_v2(batch_item_id, submitted_at DESC, feedback_id DESC);

CREATE INDEX idx_admin_feedback_supersedes
    ON admin_feedback_v2(supersedes_feedback_id)
    WHERE supersedes_feedback_id IS NOT NULL;

CREATE TRIGGER trg_admin_feedback_append_only
    BEFORE UPDATE OR DELETE ON admin_feedback_v2
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

CREATE OR REPLACE FUNCTION td_guard_admin_feedback_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    previous_item uuid;
    previous_revision integer;
BEGIN
    IF NEW.supersedes_feedback_id IS NULL THEN
        IF NEW.revision_no <> 1 THEN
            RAISE EXCEPTION '初次管理员反馈的 revision_no 必须为 1'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    SELECT batch_item_id, revision_no
      INTO previous_item, previous_revision
      FROM admin_feedback_v2
     WHERE feedback_id = NEW.supersedes_feedback_id;
    IF previous_item IS NULL THEN
        RAISE EXCEPTION '管理员反馈修订引用不存在'
            USING ERRCODE = '23503';
    END IF;
    IF previous_item <> NEW.batch_item_id
            OR NEW.revision_no <> previous_revision + 1 THEN
        RAISE EXCEPTION '管理员反馈修订必须绑定同一图片项且版本连续'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_admin_feedback_revision_guard
    BEFORE INSERT ON admin_feedback_v2
    FOR EACH ROW EXECUTE FUNCTION td_guard_admin_feedback_revision();

CREATE TABLE sample_candidate_decision_v2 (
    decision_id uuid PRIMARY KEY,
    sample_candidate_id uuid NOT NULL
        REFERENCES sample_candidate_v2(sample_candidate_id),
    decision varchar(16) NOT NULL
        CHECK (decision IN ('INCLUDE', 'EXCLUDE')),
    decision_note varchar(1000),
    supersedes_decision_id uuid
        REFERENCES sample_candidate_decision_v2(decision_id),
    decided_by uuid NOT NULL REFERENCES sys_user(user_id),
    decided_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    CONSTRAINT ck_sample_candidate_decision_not_self CHECK (
        supersedes_decision_id IS NULL
        OR supersedes_decision_id <> decision_id
    )
);

CREATE INDEX idx_sample_candidate_decision_latest
    ON sample_candidate_decision_v2(
        sample_candidate_id, decided_at DESC, decision_id DESC
    );

CREATE TRIGGER trg_sample_candidate_decision_append_only
    BEFORE UPDATE OR DELETE ON sample_candidate_decision_v2
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

ALTER TABLE sample_candidate_v2
    ADD COLUMN source_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN source_snapshot_sha256 char(64)
        CHECK (
            source_snapshot_sha256 IS NULL
            OR source_snapshot_sha256 ~ '^[0-9a-f]{64}$'
        ),
    ADD COLUMN latest_decision_id uuid
        REFERENCES sample_candidate_decision_v2(decision_id),
    ADD COLUMN included_at timestamptz,
    ADD COLUMN exported_at timestamptz,
    ADD CONSTRAINT ck_sample_candidate_exported_at CHECK (
        status <> 'EXPORTED' OR exported_at IS NOT NULL
    );

CREATE INDEX idx_sample_candidate_status_time
    ON sample_candidate_v2(status, created_at DESC, sample_candidate_id DESC);

CREATE TABLE sample_export_cleanup_event_v2 (
    cleanup_event_id uuid PRIMARY KEY,
    sample_export_job_id uuid REFERENCES sample_export_job_v2(sample_export_job_id),
    object_bucket varchar(128) NOT NULL,
    object_key varchar(1024) NOT NULL
        CHECK (object_key LIKE 'sample-exports/%'),
    operation varchar(32) NOT NULL
        CHECK (operation IN ('PACKAGE', 'MANIFEST', 'TICKET', 'ORPHAN')),
    status varchar(16) NOT NULL
        CHECK (status IN ('PENDING', 'RESOLVED', 'HOLD')),
    error_code varchar(80) NOT NULL,
    detail_digest char(64) NOT NULL
        CHECK (detail_digest ~ '^[0-9a-f]{64}$'),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    CONSTRAINT ck_sample_export_cleanup_resolution CHECK (
        (status = 'RESOLVED' AND resolved_at IS NOT NULL)
        OR (status <> 'RESOLVED' AND resolved_at IS NULL)
    )
);

CREATE TRIGGER trg_sample_export_cleanup_append_only
    BEFORE UPDATE OR DELETE ON sample_export_cleanup_event_v2
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

ALTER TABLE sample_export_job_v2
    ADD COLUMN exported_count integer NOT NULL DEFAULT 0
        CHECK (exported_count >= 0),
    ADD COLUMN failure_count integer NOT NULL DEFAULT 0
        CHECK (failure_count >= 0),
    ADD COLUMN manifest_bucket varchar(128),
    ADD COLUMN manifest_object_key varchar(1024)
        CHECK (
            manifest_object_key IS NULL
            OR manifest_object_key LIKE 'sample-exports/%'
        ),
    ADD COLUMN manifest_object_version varchar(256),
    ADD COLUMN manifest_sha256 char(64)
        CHECK (
            manifest_sha256 IS NULL
            OR manifest_sha256 ~ '^[0-9a-f]{64}$'
        ),
    ADD COLUMN manifest_size_bytes bigint
        CHECK (manifest_size_bytes IS NULL OR manifest_size_bytes > 0),
    ADD COLUMN last_error varchar(1000),
    ADD COLUMN worker_attempts integer NOT NULL DEFAULT 0
        CHECK (worker_attempts >= 0),
    ADD CONSTRAINT ck_sample_export_counts CHECK (
        exported_count + failure_count <= candidate_count
    ),
    ADD CONSTRAINT ck_sample_export_manifest CHECK (
        status NOT IN ('SUCCEEDED', 'FAILED')
        OR (
            manifest_bucket IS NOT NULL
            AND manifest_object_key IS NOT NULL
            AND manifest_sha256 IS NOT NULL
            AND manifest_size_bytes IS NOT NULL
        )
    );

ALTER TABLE sample_export_item_v2
    ADD COLUMN status varchar(16) NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'EXPORTED', 'FAILED')),
    ADD COLUMN source_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN exported_sha256 char(64)
        CHECK (
            exported_sha256 IS NULL
            OR exported_sha256 ~ '^[0-9a-f]{64}$'
        ),
    ADD COLUMN exported_size_bytes bigint
        CHECK (exported_size_bytes IS NULL OR exported_size_bytes > 0),
    ADD COLUMN error_code varchar(80),
    ADD COLUMN error_detail varchar(1000),
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN record_version bigint NOT NULL DEFAULT 1
        CHECK (record_version >= 1),
    ADD CONSTRAINT ck_sample_export_item_result CHECK (
        (status = 'EXPORTED'
            AND exported_sha256 IS NOT NULL
            AND exported_size_bytes IS NOT NULL
            AND error_code IS NULL)
        OR (status <> 'EXPORTED')
    );

CREATE INDEX idx_sample_export_item_status
    ON sample_export_item_v2(sample_export_job_id, status, sample_candidate_id);

CREATE TABLE sample_download_ticket_v2 (
    ticket_id uuid PRIMARY KEY,
    sample_export_job_id uuid NOT NULL
        REFERENCES sample_export_job_v2(sample_export_job_id),
    token_hash char(64) NOT NULL
        CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    issued_by uuid NOT NULL REFERENCES sys_user(user_id),
    issued_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'EXPIRED', 'REVOKED')),
    revoked_at timestamptz,
    UNIQUE (sample_export_job_id, token_hash),
    CONSTRAINT ck_sample_download_ticket_window CHECK (expires_at > issued_at),
    CONSTRAINT ck_sample_download_ticket_revocation CHECK (
        (status = 'REVOKED' AND revoked_at IS NOT NULL)
        OR (status <> 'REVOKED' AND revoked_at IS NULL)
    )
);

CREATE INDEX idx_sample_download_ticket_expiry
    ON sample_download_ticket_v2(status, expires_at, ticket_id);

CREATE TABLE sample_download_event_v2 (
    download_event_id uuid PRIMARY KEY,
    ticket_id uuid NOT NULL REFERENCES sample_download_ticket_v2(ticket_id),
    sample_export_job_id uuid NOT NULL
        REFERENCES sample_export_job_v2(sample_export_job_id),
    actor_id uuid REFERENCES sys_user(user_id),
    outcome varchar(16) NOT NULL
        CHECK (outcome IN ('ISSUED', 'DOWNLOADED', 'REJECTED', 'EXPIRED', 'REVOKED')),
    request_id varchar(128) NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_sample_download_event_append_only
    BEFORE UPDATE OR DELETE ON sample_download_event_v2
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

CREATE TABLE sample_external_receipt_v2 (
    receipt_id uuid PRIMARY KEY,
    sample_export_job_id uuid NOT NULL
        REFERENCES sample_export_job_v2(sample_export_job_id),
    receiver_name varchar(256) NOT NULL
        CHECK (length(trim(receiver_name)) > 0),
    external_reference varchar(512),
    receipt_note varchar(2000),
    recorded_by uuid NOT NULL REFERENCES sys_user(user_id),
    recorded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_sample_external_receipt_append_only
    BEFORE UPDATE OR DELETE ON sample_external_receipt_v2
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

INSERT INTO sys_permission(permission_id, permission_code, description)
SELECT gen_random_uuid(), permission_code, description
FROM (VALUES
    ('sample:read', '读取管理员筛选和样本候选'),
    ('sample:feedback', '创建管理员反馈'),
    ('sample:candidate:write', '加入和决策样本候选'),
    ('sample:export', '创建和查看样本导出'),
    ('sample:export:download', '签发和下载样本导出票据'),
    ('sample:external-receipt', '登记样本外部接收回执')
) permission(permission_code, description)
WHERE NOT EXISTS (
    SELECT 1
    FROM sys_permission existing
    WHERE existing.permission_code = permission.permission_code
);

INSERT INTO sys_role_permission(role_id, permission_id)
SELECT role.role_id, permission.permission_id
FROM sys_role role
JOIN sys_permission permission
  ON permission.permission_code IN (
      'sample:read', 'sample:feedback', 'sample:candidate:write',
      'sample:export', 'sample:export:download', 'sample:external-receipt'
  )
WHERE role.role_code = 'ADMINISTRATOR'
ON CONFLICT DO NOTHING;

COMMENT ON TABLE sample_candidate_v2 IS
    'R7 待整理样本候选；source_snapshot 是创建时的不可变来源快照，不等于在线数据集';
COMMENT ON TABLE sample_export_job_v2 IS
    'R7 异步导出作业；SUCCEEDED/FAILED 均要求存在清单和逐项计数，失败不得伪装为完整成功';
COMMENT ON TABLE sample_external_receipt_v2 IS
    'R7 外部交接的手工回执；不触发回调、轮询、消息订阅或训练任务';
