-- R3：手工批次对象直传、逻辑检测任务、补偿对账与草稿期聚合。

CREATE TABLE manual_batch_upload_v2 (
    upload_id uuid PRIMARY KEY,
    batch_item_id uuid NOT NULL UNIQUE REFERENCES detection_batch_item_v2(batch_item_id),
    owner_id uuid NOT NULL REFERENCES sys_user(user_id),
    file_name varchar(255) NOT NULL CHECK (length(trim(file_name)) > 0),
    expected_sha256 char(64) NOT NULL CHECK (expected_sha256 ~ '^[0-9a-f]{64}$'),
    expected_size_bytes bigint NOT NULL CHECK (expected_size_bytes > 0),
    expected_media_type varchar(64) NOT NULL CHECK (expected_media_type IN ('image/jpeg', 'image/png')),
    bucket varchar(128) NOT NULL,
    object_key varchar(1024) NOT NULL CHECK (object_key LIKE 'manual-originals/%'),
    status varchar(16) NOT NULL CHECK (status IN ('AUTHORIZED', 'CONFIRMED', 'FAILED', 'EXPIRED', 'ORPHANED')),
    expires_at timestamptz NOT NULL,
    confirmed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    UNIQUE (bucket, object_key),
    CONSTRAINT ck_manual_upload_confirmation CHECK (
        (status = 'CONFIRMED' AND confirmed_at IS NOT NULL)
        OR (status <> 'CONFIRMED' AND confirmed_at IS NULL)
    )
);

CREATE INDEX idx_manual_batch_upload_expiry
    ON manual_batch_upload_v2(status, expires_at, upload_id);

CREATE TABLE detection_task_v2 (
    detection_task_id uuid PRIMARY KEY,
    batch_item_id uuid NOT NULL UNIQUE REFERENCES detection_batch_item_v2(batch_item_id),
    status varchar(16) NOT NULL CHECK (status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
    submit_idempotency_key varchar(256) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 1 CHECK (record_version >= 1)
);

CREATE TABLE r3_compensation_event (
    compensation_id uuid PRIMARY KEY,
    batch_id uuid REFERENCES detection_batch_v2(batch_id),
    batch_item_id uuid REFERENCES detection_batch_item_v2(batch_item_id),
    operation varchar(64) NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('PENDING', 'RESOLVED', 'HOLD')),
    error_code varchar(80) NOT NULL,
    detail_digest char(64) NOT NULL CHECK (detail_digest ~ '^[0-9a-f]{64}$'),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    CONSTRAINT ck_r3_compensation_resolution CHECK (
        (status = 'RESOLVED' AND resolved_at IS NOT NULL)
        OR (status <> 'RESOLVED' AND resolved_at IS NULL)
    )
);

CREATE TRIGGER trg_r3_compensation_event_append_only
    BEFORE UPDATE OR DELETE ON r3_compensation_event
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

INSERT INTO sys_permission(permission_id, permission_code, description)
SELECT gen_random_uuid(), permission_code, description
FROM (VALUES
    ('manual-detection:read', '读取本人手工检测批次'),
    ('manual-detection:read:all', '读取全部手工检测批次'),
    ('manual-detection:write', '创建和提交本人手工检测批次')
) permission(permission_code, description)
WHERE NOT EXISTS (SELECT 1 FROM sys_permission existing
                  WHERE existing.permission_code = permission.permission_code);

INSERT INTO sys_role_permission(role_id, permission_id)
SELECT role.role_id, permission.permission_id
FROM sys_role role JOIN sys_permission permission ON
    (role.role_code = 'OPERATOR' AND permission.permission_code IN ('manual-detection:read','manual-detection:write'))
    OR (role.role_code = 'SYSTEM_OPERATOR' AND permission.permission_code IN ('manual-detection:read','manual-detection:read:all','manual-detection:write'))
ON CONFLICT DO NOTHING;

-- R2 函数只处理运行期聚合；R3 增加手工草稿、上传和就绪状态。
CREATE OR REPLACE FUNCTION td_recompute_detection_batch_v2(p_batch_id uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    summary record;
    current_batch record;
    next_status varchar(32);
BEGIN
    SELECT status, source, legacy_read_only INTO current_batch
    FROM detection_batch_v2 WHERE batch_id = p_batch_id FOR UPDATE;

    SELECT
        count(*)::integer AS total,
        count(*) FILTER (WHERE status IN ('COMPLETED', 'QUALITY_REJECTED', 'FAILED', 'CANCELLED'))::integer AS completed,
        count(*) FILTER (WHERE status = 'COMPLETED' AND algorithm_outcome = 'UNQUALIFIED')::integer AS defect_suspected,
        count(*) FILTER (WHERE status = 'COMPLETED' AND algorithm_outcome = 'QUALIFIED')::integer AS normal,
        count(*) FILTER (WHERE status = 'COMPLETED' AND algorithm_outcome = 'INCONCLUSIVE')::integer AS inconclusive,
        count(*) FILTER (WHERE status = 'QUALITY_REJECTED')::integer AS quality_rejected,
        count(*) FILTER (WHERE status = 'FAILED')::integer AS technical_failed,
        count(*) FILTER (WHERE status IN ('PENDING_UPLOAD', 'UPLOADING'))::integer AS uploading,
        count(*) FILTER (WHERE status = 'READY')::integer AS ready,
        count(*) FILTER (WHERE status IN ('QUEUED', 'PROCESSING'))::integer AS active
    INTO summary FROM detection_batch_item_v2 WHERE batch_id = p_batch_id;

    next_status := CASE
        WHEN current_batch.source = 'MANUAL_UPLOAD'
             AND current_batch.status IN ('DRAFT', 'UPLOADING', 'READY')
             AND summary.active = 0
            THEN CASE
                WHEN summary.total = 0 THEN 'DRAFT'
                WHEN summary.uploading > 0 THEN 'UPLOADING'
                WHEN summary.ready = summary.total THEN 'READY'
                ELSE 'UPLOADING'
            END
        WHEN summary.total = 0 THEN 'FAILED'
        WHEN summary.completed < summary.total THEN 'PROCESSING'
        WHEN summary.technical_failed = summary.total THEN 'FAILED'
        WHEN summary.technical_failed > 0 OR summary.quality_rejected > 0 THEN 'PARTIALLY_COMPLETED'
        ELSE 'COMPLETED'
    END;

    UPDATE detection_batch_v2 SET
        total_count = summary.total,
        completed_count = summary.completed,
        defect_suspected_count = summary.defect_suspected,
        normal_count = summary.normal,
        inconclusive_count = summary.inconclusive,
        quality_rejected_count = summary.quality_rejected,
        technical_failed_count = summary.technical_failed,
        status = next_status,
        updated_at = now(),
        record_version = record_version + 1
    WHERE batch_id = p_batch_id;
END;
$$;
