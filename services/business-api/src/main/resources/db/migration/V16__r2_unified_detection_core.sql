-- R2：统一批次核心、历史回填、影子读证据和外部模型来源。
-- 本迁移只追加新事实并放宽旧模型来源字段，不删除或改写历史业务引用。

CREATE SEQUENCE detection_batch_number_seq START WITH 1;

CREATE TABLE detection_batch_v2 (
    batch_id uuid PRIMARY KEY,
    batch_no varchar(32) NOT NULL UNIQUE,
    source varchar(32) NOT NULL
        CHECK (source IN ('MANUAL_UPLOAD', 'PRODUCTION_CAPTURE')),
    created_by uuid REFERENCES sys_user(user_id),
    usage_stage varchar(32) NOT NULL CHECK (
        usage_stage IN (
            'NEW_BLADE', 'AFTER_ONE_WHEEL', 'AFTER_TWO_WHEELS',
            'AFTER_THREE_WHEELS', 'OTHER', 'UNSPECIFIED'
        )
    ),
    usage_stage_note varchar(200),
    status varchar(32) NOT NULL CHECK (
        status IN (
            'DRAFT', 'UPLOADING', 'READY', 'PROCESSING', 'COMPLETED',
            'PARTIALLY_COMPLETED', 'FAILED', 'CANCELLED'
        )
    ),
    total_count integer NOT NULL DEFAULT 0 CHECK (total_count >= 0),
    completed_count integer NOT NULL DEFAULT 0 CHECK (completed_count >= 0),
    defect_suspected_count integer NOT NULL DEFAULT 0
        CHECK (defect_suspected_count >= 0),
    normal_count integer NOT NULL DEFAULT 0 CHECK (normal_count >= 0),
    inconclusive_count integer NOT NULL DEFAULT 0 CHECK (inconclusive_count >= 0),
    quality_rejected_count integer NOT NULL DEFAULT 0
        CHECK (quality_rejected_count >= 0),
    technical_failed_count integer NOT NULL DEFAULT 0
        CHECK (technical_failed_count >= 0),
    legacy_capture_id uuid UNIQUE REFERENCES capture_event(capture_id),
    legacy_read_only boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    CONSTRAINT ck_detection_batch_counts CHECK (
        completed_count <= total_count
        AND defect_suspected_count + normal_count + inconclusive_count
            + quality_rejected_count + technical_failed_count <= total_count
    ),
    CONSTRAINT ck_detection_batch_legacy CHECK (
        NOT legacy_read_only OR legacy_capture_id IS NOT NULL
    )
);

CREATE TABLE detection_batch_item_v2 (
    batch_item_id uuid PRIMARY KEY,
    batch_id uuid NOT NULL REFERENCES detection_batch_v2(batch_id),
    capture_id uuid UNIQUE REFERENCES capture_event(capture_id),
    image_id uuid NOT NULL UNIQUE REFERENCES image_object(image_id),
    status varchar(32) NOT NULL CHECK (
        status IN (
            'PENDING_UPLOAD', 'UPLOADING', 'READY', 'QUEUED', 'PROCESSING',
            'COMPLETED', 'QUALITY_REJECTED', 'FAILED', 'CANCELLED'
        )
    ),
    algorithm_outcome varchar(24) CHECK (
        algorithm_outcome IS NULL
        OR algorithm_outcome IN ('QUALIFIED', 'UNQUALIFIED', 'INCONCLUSIVE')
    ),
    quick_review_decision varchar(32) CHECK (
        quick_review_decision IS NULL
        OR quick_review_decision IN (
            'DEFECT_CONFIRMED', 'NO_DEFECT_CONFIRMED', 'UNABLE_TO_DETERMINE'
        )
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    UNIQUE (batch_id, image_id)
);

CREATE INDEX idx_detection_batch_v2_owner_time
    ON detection_batch_v2(created_by, created_at DESC, batch_id);
CREATE INDEX idx_detection_batch_v2_status_time
    ON detection_batch_v2(status, created_at, batch_id);
CREATE INDEX idx_detection_batch_item_v2_batch
    ON detection_batch_item_v2(batch_id, created_at, batch_item_id);
CREATE INDEX idx_detection_batch_item_v2_status
    ON detection_batch_item_v2(status, updated_at, batch_item_id);

CREATE TABLE image_quality_result_v2 (
    quality_result_id uuid PRIMARY KEY,
    batch_item_id uuid NOT NULL REFERENCES detection_batch_item_v2(batch_item_id),
    overall varchar(16) NOT NULL CHECK (overall IN ('ACCEPTED', 'WARNING', 'REJECTED')),
    checker_version varchar(100) NOT NULL CHECK (length(trim(checker_version)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (batch_item_id, checker_version)
);

CREATE TABLE image_quality_check_v2 (
    quality_check_id uuid PRIMARY KEY,
    quality_result_id uuid NOT NULL REFERENCES image_quality_result_v2(quality_result_id),
    check_type varchar(32) NOT NULL CHECK (
        check_type IN ('DECODABLE', 'BLADE_PRESENT', 'BLADE_COMPLETE', 'BLUR', 'EXPOSURE')
    ),
    status varchar(16) NOT NULL CHECK (status IN ('PASS', 'WARNING', 'FAIL', 'NOT_RUN')),
    rule_id varchar(100) NOT NULL CHECK (length(trim(rule_id)) > 0),
    reason_code varchar(100) NOT NULL CHECK (length(trim(reason_code)) > 0),
    measurement numeric,
    threshold numeric,
    user_hint varchar(300) NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (quality_result_id, check_type)
);

CREATE TABLE quick_feedback_v2 (
    feedback_id uuid PRIMARY KEY,
    batch_item_id uuid NOT NULL REFERENCES detection_batch_item_v2(batch_item_id),
    decision varchar(32) NOT NULL CHECK (
        decision IN ('DEFECT_CONFIRMED', 'NO_DEFECT_CONFIRMED', 'UNABLE_TO_DETERMINE')
    ),
    submitted_by uuid REFERENCES sys_user(user_id),
    idempotency_key varchar(200) NOT NULL,
    supersedes_id uuid REFERENCES quick_feedback_v2(feedback_id),
    submitted_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (submitted_by, idempotency_key),
    CONSTRAINT ck_quick_feedback_not_self CHECK (
        supersedes_id IS NULL OR supersedes_id <> feedback_id
    )
);

CREATE TABLE admin_feedback_v2 (
    feedback_id uuid PRIMARY KEY,
    batch_item_id uuid NOT NULL REFERENCES detection_batch_item_v2(batch_item_id),
    label varchar(40) NOT NULL CHECK (
        label IN (
            'CORRECT_DETECTION', 'FALSE_POSITIVE', 'FALSE_NEGATIVE',
            'LOCALIZATION_INACCURATE', 'IMAGE_UNUSABLE', 'UNCONFIRMED'
        )
    ),
    note varchar(2000),
    annotation_image_id uuid REFERENCES image_object(image_id),
    source_review_record_id uuid REFERENCES review_record(review_record_id),
    submitted_by uuid REFERENCES sys_user(user_id),
    idempotency_key varchar(200) NOT NULL,
    submitted_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (submitted_by, idempotency_key)
);

CREATE TABLE sample_candidate_v2 (
    sample_candidate_id uuid PRIMARY KEY,
    batch_item_id uuid NOT NULL REFERENCES detection_batch_item_v2(batch_item_id),
    feedback_id uuid NOT NULL REFERENCES admin_feedback_v2(feedback_id),
    status varchar(16) NOT NULL CHECK (status IN ('PENDING', 'INCLUDED', 'EXCLUDED', 'EXPORTED')),
    decision_note varchar(1000),
    decided_by uuid REFERENCES sys_user(user_id),
    decided_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    UNIQUE (batch_item_id, feedback_id),
    CONSTRAINT ck_sample_candidate_decision CHECK (
        (status = 'PENDING' AND decided_by IS NULL AND decided_at IS NULL)
        OR (status <> 'PENDING' AND decided_by IS NOT NULL AND decided_at IS NOT NULL)
    )
);

CREATE TABLE sample_export_job_v2 (
    sample_export_job_id uuid PRIMARY KEY,
    filter_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    candidate_count integer NOT NULL CHECK (candidate_count > 0),
    status varchar(16) NOT NULL CHECK (
        status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'EXPIRED')
    ),
    package_bucket varchar(128),
    package_object_key varchar(1024),
    package_object_version varchar(256),
    package_sha256 char(64) CHECK (
        package_sha256 IS NULL OR package_sha256 ~ '^[0-9a-f]{64}$'
    ),
    package_size_bytes bigint CHECK (package_size_bytes IS NULL OR package_size_bytes > 0),
    package_media_type varchar(64),
    failed_candidate_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    requested_by uuid REFERENCES sys_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    record_version bigint NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    CONSTRAINT ck_sample_export_package CHECK (
        status <> 'SUCCEEDED'
        OR (
            package_bucket IS NOT NULL AND package_object_key IS NOT NULL
            AND package_sha256 IS NOT NULL AND package_size_bytes IS NOT NULL
            AND package_media_type IN ('application/zip', 'application/json')
        )
    )
);

CREATE TABLE sample_export_item_v2 (
    sample_export_job_id uuid NOT NULL
        REFERENCES sample_export_job_v2(sample_export_job_id),
    sample_candidate_id uuid NOT NULL
        REFERENCES sample_candidate_v2(sample_candidate_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (sample_export_job_id, sample_candidate_id)
);

CREATE TABLE model_upload_session_v2 (
    model_upload_id uuid PRIMARY KEY,
    model_version_label varchar(100) NOT NULL CHECK (length(trim(model_version_label)) > 0),
    description varchar(1000),
    quarantine_bucket varchar(128) NOT NULL,
    quarantine_object_key varchar(1024) NOT NULL CHECK (
        quarantine_object_key LIKE 'model-quarantine/%'
    ),
    quarantine_object_version varchar(256),
    declared_sha256 char(64) NOT NULL CHECK (declared_sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    media_type varchar(64) NOT NULL CHECK (media_type IN ('application/zip', 'application/json')),
    status varchar(24) NOT NULL CHECK (
        status IN ('AWAITING_UPLOAD', 'UPLOADED', 'VALIDATING', 'VALIDATED', 'REJECTED', 'EXPIRED')
    ),
    created_by uuid REFERENCES sys_user(user_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    record_version bigint NOT NULL DEFAULT 1 CHECK (record_version >= 1),
    UNIQUE (quarantine_bucket, quarantine_object_key, declared_sha256)
);

CREATE TABLE r2_migration_failure (
    failure_id uuid PRIMARY KEY,
    source_kind varchar(40) NOT NULL,
    source_id uuid NOT NULL,
    error_code varchar(80) NOT NULL,
    detail_digest char(64) NOT NULL CHECK (detail_digest ~ '^[0-9a-f]{64}$'),
    status varchar(16) NOT NULL DEFAULT 'HOLD' CHECK (status IN ('HOLD', 'RESOLVED')),
    first_observed_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    UNIQUE (source_kind, source_id, error_code),
    CONSTRAINT ck_r2_migration_failure_resolution CHECK (
        (status = 'HOLD' AND resolved_at IS NULL)
        OR (status = 'RESOLVED' AND resolved_at IS NOT NULL)
    )
);

CREATE TABLE r2_shadow_read_difference (
    difference_id uuid PRIMARY KEY,
    source_kind varchar(40) NOT NULL,
    source_id uuid NOT NULL,
    field_name varchar(100) NOT NULL,
    legacy_digest char(64) CHECK (legacy_digest IS NULL OR legacy_digest ~ '^[0-9a-f]{64}$'),
    core_digest char(64) CHECK (core_digest IS NULL OR core_digest ~ '^[0-9a-f]{64}$'),
    status varchar(16) NOT NULL DEFAULT 'HOLD' CHECK (status IN ('HOLD', 'EXPLAINED')),
    observed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_kind, source_id, field_name, legacy_digest, core_digest)
);

CREATE TABLE r2_operational_event (
    event_id uuid PRIMARY KEY,
    event_type varchar(80) NOT NULL CHECK (event_type ~ '\.v2$'),
    aggregate_type varchar(40) NOT NULL,
    aggregate_id uuid NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('RECORDED', 'HOLD')),
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_r2_operational_event_safe CHECK (
        NOT (detail ? 'image')
        AND NOT (detail ? 'token')
        AND NOT (detail ? 'signed_url')
        AND NOT (detail ? 'signature')
        AND NOT (detail ? 'base64')
    )
);

CREATE OR REPLACE FUNCTION td_record_r2_operational_event()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    aggregate_id uuid;
    aggregate_type varchar(40);
    event_type varchar(80);
    event_status varchar(16);
    version_key text;
    digest text;
BEGIN
    CASE TG_TABLE_NAME
        WHEN 'detection_batch_v2' THEN
            aggregate_id := NEW.batch_id;
            aggregate_type := 'DETECTION_BATCH';
            event_type := 'detection.batch.changed.v2';
            event_status := CASE WHEN NEW.status = 'FAILED' THEN 'HOLD' ELSE 'RECORDED' END;
            version_key := NEW.record_version::text;
        WHEN 'detection_batch_item_v2' THEN
            aggregate_id := NEW.batch_item_id;
            aggregate_type := 'DETECTION_BATCH_ITEM';
            event_type := 'detection.batch-item.changed.v2';
            event_status := CASE WHEN NEW.status = 'FAILED' THEN 'HOLD' ELSE 'RECORDED' END;
            version_key := NEW.record_version::text;
        WHEN 'r2_migration_failure' THEN
            aggregate_id := NEW.source_id;
            aggregate_type := 'MIGRATION_FAILURE';
            event_type := 'migration.failure-recorded.v2';
            event_status := 'HOLD';
            version_key := NEW.error_code;
        WHEN 'r2_shadow_read_difference' THEN
            aggregate_id := NEW.source_id;
            aggregate_type := 'SHADOW_READ_DIFFERENCE';
            event_type := 'shadow-read.difference-recorded.v2';
            event_status := 'HOLD';
            version_key := NEW.field_name || ':' || COALESCE(NEW.core_digest, 'unknown');
        ELSE
            RAISE EXCEPTION 'unsupported R2 operational event source: %', TG_TABLE_NAME;
    END CASE;

    digest := md5(TG_TABLE_NAME || ':' || aggregate_id::text || ':' || version_key);
    INSERT INTO r2_operational_event(
        event_id, event_type, aggregate_type, aggregate_id, status, detail
    ) VALUES (
        (
            substr(digest, 1, 8) || '-' || substr(digest, 9, 4) || '-4' ||
            substr(digest, 14, 3) || '-8' || substr(digest, 18, 3) || '-' ||
            substr(digest, 21, 12)
        )::uuid,
        event_type,
        aggregate_type,
        aggregate_id,
        event_status,
        jsonb_build_object('source_table', TG_TABLE_NAME, 'state', event_status)
    ) ON CONFLICT (event_id) DO NOTHING;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_detection_batch_v2_operational_event
    AFTER INSERT OR UPDATE OF status ON detection_batch_v2
    FOR EACH ROW EXECUTE FUNCTION td_record_r2_operational_event();
CREATE TRIGGER trg_detection_batch_item_v2_operational_event
    AFTER INSERT OR UPDATE OF status ON detection_batch_item_v2
    FOR EACH ROW EXECUTE FUNCTION td_record_r2_operational_event();
CREATE TRIGGER trg_r2_migration_failure_operational_event
    AFTER INSERT ON r2_migration_failure
    FOR EACH ROW EXECUTE FUNCTION td_record_r2_operational_event();
CREATE TRIGGER trg_r2_shadow_difference_operational_event
    AFTER INSERT ON r2_shadow_read_difference
    FOR EACH ROW EXECUTE FUNCTION td_record_r2_operational_event();

CREATE TRIGGER trg_image_quality_result_v2_append_only
    BEFORE UPDATE OR DELETE ON image_quality_result_v2
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();
CREATE TRIGGER trg_image_quality_check_v2_append_only
    BEFORE UPDATE OR DELETE ON image_quality_check_v2
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();
CREATE TRIGGER trg_quick_feedback_v2_append_only
    BEFORE UPDATE OR DELETE ON quick_feedback_v2
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();
CREATE TRIGGER trg_admin_feedback_v2_append_only
    BEFORE UPDATE OR DELETE ON admin_feedback_v2
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();
CREATE TRIGGER trg_r2_migration_failure_append_only
    BEFORE UPDATE OR DELETE ON r2_migration_failure
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();
CREATE TRIGGER trg_r2_shadow_difference_append_only
    BEFORE UPDATE OR DELETE ON r2_shadow_read_difference
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();
CREATE TRIGGER trg_r2_operational_event_append_only
    BEFORE UPDATE OR DELETE ON r2_operational_event
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

-- 旧模型保持完整内部来源；新外部上传模型不得再依赖旧数据集或训练运行。
ALTER TABLE model_version
    ALTER COLUMN dataset_version_id DROP NOT NULL,
    ADD COLUMN source_kind varchar(32) NOT NULL DEFAULT 'LEGACY_INTERNAL',
    ADD COLUMN model_upload_id uuid REFERENCES model_upload_session_v2(model_upload_id),
    ADD COLUMN external_source_snapshot jsonb,
    ADD CONSTRAINT ck_model_version_source_kind CHECK (
        source_kind IN ('LEGACY_INTERNAL', 'EXTERNAL_UPLOAD')
    ),
    ADD CONSTRAINT ck_model_version_source_complete_exclusive CHECK (
        (
            source_kind = 'LEGACY_INTERNAL'
            AND dataset_version_id IS NOT NULL
            AND model_upload_id IS NULL
            AND external_source_snapshot IS NULL
        )
        OR (
            source_kind = 'EXTERNAL_UPLOAD'
            AND dataset_version_id IS NULL
            AND training_run_id IS NULL
            AND model_upload_id IS NOT NULL
            AND external_source_snapshot IS NOT NULL
            AND external_source_snapshot ? 'source_system'
            AND external_source_snapshot ? 'source_version'
            AND external_source_snapshot ? 'exported_at'
            AND external_source_snapshot ? 'sha256'
            AND external_source_snapshot->>'sha256' ~ '^[0-9a-f]{64}$'
        )
    );

COMMENT ON COLUMN model_version.source_kind IS
    'LEGACY_INTERNAL 为只读历史内部来源；EXTERNAL_UPLOAD 为第二版隔离上传来源';

-- 取消能力不再向任何人员角色分配；模型审批使用模型专属权限。
INSERT INTO sys_permission(permission_id, permission_code, description)
SELECT (
        substr(md5('tool-defect-permission:model:approve'), 1, 8) || '-' ||
        substr(md5('tool-defect-permission:model:approve'), 9, 4) || '-4' ||
        substr(md5('tool-defect-permission:model:approve'), 14, 3) || '-8' ||
        substr(md5('tool-defect-permission:model:approve'), 18, 3) || '-' ||
        substr(md5('tool-defect-permission:model:approve'), 21, 12)
    )::uuid,
    'model:approve',
    '批准模型验证和生产启用请求'
WHERE NOT EXISTS (
    SELECT 1 FROM sys_permission WHERE permission_code = 'model:approve'
);

DELETE FROM sys_role_permission mapping
USING sys_permission permission
WHERE mapping.permission_id = permission.permission_id
  AND permission.permission_code IN (
      'dataset:create', 'dataset:approve', 'training:create', 'training:read'
  );

INSERT INTO sys_role_permission(role_id, permission_id)
SELECT role.role_id, permission.permission_id
FROM sys_role role
JOIN sys_permission permission ON permission.permission_code = 'model:approve'
WHERE role.role_code IN ('MODEL_APPROVER', 'SYSTEM_OPERATOR')
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION td_recompute_detection_batch_v2(p_batch_id uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    summary record;
    next_status varchar(32);
BEGIN
    SELECT
        count(*)::integer AS total,
        count(*) FILTER (WHERE status IN ('COMPLETED', 'QUALITY_REJECTED', 'FAILED', 'CANCELLED'))::integer AS completed,
        count(*) FILTER (WHERE status = 'COMPLETED' AND algorithm_outcome = 'UNQUALIFIED')::integer AS defect_suspected,
        count(*) FILTER (WHERE status = 'COMPLETED' AND algorithm_outcome = 'QUALIFIED')::integer AS normal,
        count(*) FILTER (WHERE status = 'COMPLETED' AND algorithm_outcome = 'INCONCLUSIVE')::integer AS inconclusive,
        count(*) FILTER (WHERE status = 'QUALITY_REJECTED')::integer AS quality_rejected,
        count(*) FILTER (WHERE status = 'FAILED')::integer AS technical_failed
    INTO summary
    FROM detection_batch_item_v2
    WHERE batch_id = p_batch_id;

    next_status := CASE
        WHEN summary.total = 0 THEN 'FAILED'
        WHEN summary.completed < summary.total THEN 'PROCESSING'
        WHEN summary.technical_failed = summary.total THEN 'FAILED'
        WHEN summary.technical_failed > 0 OR summary.quality_rejected > 0 THEN 'PARTIALLY_COMPLETED'
        ELSE 'COMPLETED'
    END;

    UPDATE detection_batch_v2
    SET total_count = summary.total,
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

CREATE OR REPLACE FUNCTION td_recompute_detection_batch_v2_trigger()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM td_recompute_detection_batch_v2(COALESCE(NEW.batch_id, OLD.batch_id));
    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE TRIGGER trg_detection_batch_item_v2_recompute
    AFTER INSERT OR UPDATE OF status, algorithm_outcome OR DELETE
    ON detection_batch_item_v2
    FOR EACH ROW EXECUTE FUNCTION td_recompute_detection_batch_v2_trigger();

CREATE OR REPLACE FUNCTION td_backfill_legacy_captures_v2()
RETURNS TABLE(inserted_batches integer, inserted_items integer, held_captures integer)
LANGUAGE plpgsql
AS $$
DECLARE
    before_batches bigint;
    before_items bigint;
BEGIN
    SELECT count(*) INTO before_batches FROM detection_batch_v2;
    SELECT count(*) INTO before_items FROM detection_batch_item_v2;

    INSERT INTO detection_batch_v2(
        batch_id, batch_no, source, created_by, usage_stage, status,
        legacy_capture_id, legacy_read_only, created_at, updated_at
    )
    SELECT
        capture.capture_id,
        'JC-' || to_char(capture.captured_at AT TIME ZONE 'UTC', 'YYYYMMDD') || '-' ||
            lpad(nextval('detection_batch_number_seq')::text, 5, '0'),
        'PRODUCTION_CAPTURE',
        NULL,
        'UNSPECIFIED',
        CASE
            WHEN capture.status = 'FAILED' THEN 'FAILED'
            WHEN capture.status = 'FINALIZED' THEN 'COMPLETED'
            ELSE 'PROCESSING'
        END,
        capture.capture_id,
        true,
        capture.created_at,
        capture.updated_at
    FROM capture_event capture
    WHERE NOT EXISTS (
        SELECT 1 FROM detection_batch_v2 batch
        WHERE batch.legacy_capture_id = capture.capture_id
    )
    ORDER BY capture.captured_at, capture.capture_id;

    INSERT INTO detection_batch_item_v2(
        batch_item_id, batch_id, capture_id, image_id, status,
        algorithm_outcome, created_at, updated_at
    )
    SELECT
        raw.image_id,
        capture.capture_id,
        capture.capture_id,
        raw.image_id,
        CASE
            WHEN capture.status = 'FAILED' THEN 'FAILED'
            WHEN capture.status = 'FINALIZED' THEN 'COMPLETED'
            WHEN raw.state <> 'AVAILABLE' THEN 'FAILED'
            ELSE 'PROCESSING'
        END,
        CASE capture.current_disposition
            WHEN 'PASS' THEN 'QUALIFIED'
            WHEN 'FAIL' THEN 'UNQUALIFIED'
            WHEN 'HOLD' THEN 'INCONCLUSIVE'
            ELSE NULL
        END,
        raw.created_at,
        raw.updated_at
    FROM capture_event capture
    JOIN LATERAL (
        SELECT min(image.image_id::text)::uuid AS image_id
        FROM image_object image
        WHERE image.capture_id = capture.capture_id AND image.kind = 'RAW'
        HAVING count(*) = 1
    ) selected ON true
    JOIN image_object raw ON raw.image_id = selected.image_id
    WHERE NOT EXISTS (
        SELECT 1 FROM detection_batch_item_v2 item
        WHERE item.capture_id = capture.capture_id
    );

    INSERT INTO r2_migration_failure(
        failure_id, source_kind, source_id, error_code, detail_digest
    )
    SELECT
        (
            substr(md5('r2-capture:' || capture.capture_id::text), 1, 8) || '-' ||
            substr(md5('r2-capture:' || capture.capture_id::text), 9, 4) || '-4' ||
            substr(md5('r2-capture:' || capture.capture_id::text), 14, 3) || '-8' ||
            substr(md5('r2-capture:' || capture.capture_id::text), 18, 3) || '-' ||
            substr(md5('r2-capture:' || capture.capture_id::text), 21, 12)
        )::uuid,
        'LEGACY_CAPTURE',
        capture.capture_id,
        CASE WHEN count(raw.image_id) = 0
            THEN 'TD-R2-RAW-IMAGE-MISSING'
            ELSE 'TD-R2-MULTI-VIEW-READ-ONLY'
        END,
        md5(capture.capture_id::text || ':' || count(raw.image_id)::text || ':' || capture.status) ||
        md5('r2:' || capture.capture_id::text || ':' || count(raw.image_id)::text || ':' || capture.status)
    FROM capture_event capture
    LEFT JOIN image_object raw
      ON raw.capture_id = capture.capture_id AND raw.kind = 'RAW'
    GROUP BY capture.capture_id, capture.status
    HAVING count(raw.image_id) <> 1
    ON CONFLICT (source_kind, source_id, error_code) DO NOTHING;

    FOR inserted_batches, inserted_items, held_captures IN
        SELECT
            (SELECT count(*) FROM detection_batch_v2) - before_batches,
            (SELECT count(*) FROM detection_batch_item_v2) - before_items,
            (SELECT count(*) FROM r2_migration_failure WHERE status = 'HOLD')
    LOOP
        RETURN NEXT;
    END LOOP;
END;
$$;

SELECT * FROM td_backfill_legacy_captures_v2();

CREATE OR REPLACE FUNCTION td_capture_shadow_differences_v2()
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    inserted_count integer;
BEGIN
    INSERT INTO r2_shadow_read_difference(
        difference_id, source_kind, source_id, field_name,
        legacy_digest, core_digest
    )
    SELECT
        (
            substr(md5('r2-shadow:' || capture.capture_id::text || ':status'), 1, 8) || '-' ||
            substr(md5('r2-shadow:' || capture.capture_id::text || ':status'), 9, 4) || '-4' ||
            substr(md5('r2-shadow:' || capture.capture_id::text || ':status'), 14, 3) || '-8' ||
            substr(md5('r2-shadow:' || capture.capture_id::text || ':status'), 18, 3) || '-' ||
            substr(md5('r2-shadow:' || capture.capture_id::text || ':status'), 21, 12)
        )::uuid,
        'LEGACY_CAPTURE', capture.capture_id, 'terminal_status',
        md5(CASE
            WHEN capture.status = 'FAILED' THEN 'FAILED'
            WHEN capture.status = 'FINALIZED' THEN 'COMPLETED'
            ELSE 'PROCESSING'
        END),
        md5(batch.status)
    FROM capture_event capture
    JOIN detection_batch_v2 batch ON batch.legacy_capture_id = capture.capture_id
    WHERE CASE
        WHEN capture.status = 'FAILED' THEN 'FAILED'
        WHEN capture.status = 'FINALIZED' THEN 'COMPLETED'
        ELSE 'PROCESSING'
    END <> batch.status
      AND NOT EXISTS (
          SELECT 1 FROM r2_shadow_read_difference existing
          WHERE existing.source_kind = 'LEGACY_CAPTURE'
            AND existing.source_id = capture.capture_id
            AND existing.field_name = 'terminal_status'
            AND existing.legacy_digest = md5(CASE
                WHEN capture.status = 'FAILED' THEN 'FAILED'
                WHEN capture.status = 'FINALIZED' THEN 'COMPLETED'
                ELSE 'PROCESSING'
            END)
            AND existing.core_digest = md5(batch.status)
      );
    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    RETURN inserted_count;
END;
$$;

COMMENT ON FUNCTION td_backfill_legacy_captures_v2() IS
    '可重复执行；单原图采集确定性回填，多原图或缺图采集进入稳定 HOLD 清单';
COMMENT ON FUNCTION td_capture_shadow_differences_v2() IS
    '只记录摘要和标识，不记录图片、令牌或签名地址';

-- 第一版兼容写：只在全部图片已知的 READY 边界同步，禁止逐张到达时挑选首图。
CREATE OR REPLACE FUNCTION td_sync_legacy_capture_v2_trigger()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM td_backfill_legacy_captures_v2();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_capture_ready_sync_v2
    AFTER UPDATE OF status ON capture_event
    FOR EACH ROW
    WHEN (NEW.status IN ('READY', 'SUBMITTED'))
    EXECUTE FUNCTION td_sync_legacy_capture_v2_trigger();

CREATE OR REPLACE FUNCTION td_sync_legacy_detection_result_v2()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE detection_batch_item_v2 item
    SET status = 'COMPLETED',
        algorithm_outcome = NEW.algorithm_outcome,
        updated_at = now(),
        record_version = item.record_version + 1
    FROM detection_task task
    WHERE task.detection_task_id = NEW.detection_task_id
      AND item.capture_id = task.capture_id;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_detection_result_sync_v2
    AFTER INSERT ON detection_result
    FOR EACH ROW EXECUTE FUNCTION td_sync_legacy_detection_result_v2();

CREATE OR REPLACE FUNCTION td_sync_legacy_detection_failure_v2()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE detection_batch_item_v2
    SET status = 'FAILED',
        algorithm_outcome = NULL,
        updated_at = now(),
        record_version = record_version + 1
    WHERE capture_id = NEW.capture_id;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_detection_failure_sync_v2
    AFTER UPDATE OF status ON detection_task
    FOR EACH ROW
    WHEN (NEW.status = 'DEAD' AND OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION td_sync_legacy_detection_failure_v2();

CREATE OR REPLACE FUNCTION td_sync_legacy_review_v2()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO admin_feedback_v2(
        feedback_id, batch_item_id, label, note,
        annotation_image_id, source_review_record_id,
        submitted_by, idempotency_key, submitted_at
    )
    SELECT
        NEW.review_record_id,
        item.batch_item_id,
        'UNCONFIRMED',
        NEW.comment,
        NEW.annotation_image_id,
        NEW.review_record_id,
        CASE WHEN EXISTS (
            SELECT 1 FROM sys_user WHERE user_id = NEW.reviewer_id
        ) THEN NEW.reviewer_id ELSE NULL END,
        'legacy-review:' || NEW.review_record_id::text,
        NEW.submitted_at
    FROM review_task task
    JOIN detection_batch_item_v2 item ON item.capture_id = task.capture_id
    WHERE task.review_task_id = NEW.review_task_id
    ON CONFLICT (feedback_id) DO NOTHING;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_review_record_sync_v2
    AFTER INSERT ON review_record
    FOR EACH ROW EXECUTE FUNCTION td_sync_legacy_review_v2();
