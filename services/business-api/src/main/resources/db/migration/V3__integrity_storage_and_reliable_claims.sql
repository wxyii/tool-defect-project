-- P2-B02~B04：补齐跨实体一致性、不可变事实、上传会话和可靠领取租约。

CREATE TABLE organization (
    organization_id uuid PRIMARY KEY,
    organization_code varchar(64) NOT NULL UNIQUE,
    organization_name varchar(128) NOT NULL,
    status varchar(24) NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 0 CHECK (record_version >= 0)
);

-- 已有部署向前迁移时先归入明确的待整理组织，后续由受控配置流程重新归属。
INSERT INTO organization(
    organization_id,
    organization_code,
    organization_name,
    status
)
VALUES (
    '00000000-0000-7000-8000-000000000000',
    'migration-default',
    '迁移默认组织',
    'INACTIVE'
);

ALTER TABLE production_line
    ADD COLUMN organization_id uuid;
UPDATE production_line
SET organization_id = '00000000-0000-7000-8000-000000000000'
WHERE organization_id IS NULL;
ALTER TABLE production_line
    ALTER COLUMN organization_id SET NOT NULL,
    ADD CONSTRAINT fk_production_line_organization
        FOREIGN KEY (organization_id) REFERENCES organization(organization_id);
ALTER TABLE production_line
    DROP CONSTRAINT production_line_line_code_key,
    ADD CONSTRAINT uq_production_line_org_code
        UNIQUE (organization_id, line_code);

ALTER TABLE device
    ADD CONSTRAINT ck_device_status
    CHECK (status IN ('ONLINE', 'OFFLINE', 'DEGRADED', 'REVOKED'));

ALTER TABLE capture_event
    ADD CONSTRAINT uq_capture_identity_station UNIQUE (capture_id, station_id),
    ADD CONSTRAINT ck_capture_disposition_pair CHECK (
        (current_disposition_id IS NULL AND current_disposition IS NULL)
        OR (current_disposition_id IS NOT NULL AND current_disposition IS NOT NULL)
    );

ALTER TABLE disposition_record
    ADD CONSTRAINT uq_disposition_capture_value
    UNIQUE (disposition_id, capture_id, disposition);
ALTER TABLE capture_event
    DROP CONSTRAINT fk_capture_current_disposition,
    ADD CONSTRAINT fk_capture_current_disposition
    FOREIGN KEY (current_disposition_id, capture_id, current_disposition)
    REFERENCES disposition_record(disposition_id, capture_id, disposition);

ALTER TABLE detection_attempt
    ADD CONSTRAINT uq_attempt_identity_task
    UNIQUE (attempt_id, detection_task_id);
ALTER TABLE detection_result
    DROP CONSTRAINT detection_result_accepted_attempt_id_fkey,
    ADD CONSTRAINT fk_detection_result_accepted_attempt
    FOREIGN KEY (accepted_attempt_id, detection_task_id)
    REFERENCES detection_attempt(attempt_id, detection_task_id),
    ADD CONSTRAINT ck_rejected_preprocess_is_inconclusive CHECK (
        preprocess_quality <> 'REJECTED'
        OR algorithm_outcome = 'INCONCLUSIVE'
    );

-- PostgreSQL 会按 63 字节标识符上限截断自动生成的多列唯一约束名。
-- 不猜测截断后的名称，而是按冻结的 V1 约束定义精确定位，确保空库和
-- 已有 V2 数据库使用相同的向前迁移路径。
DO $$
DECLARE
    artifact_constraint_name text;
BEGIN
    SELECT conname
    INTO artifact_constraint_name
    FROM pg_constraint
    WHERE conrelid = 'model_version'::regclass
      AND contype = 'u'
      AND pg_get_constraintdef(oid) =
          'UNIQUE (artifact_bucket, artifact_object_key, artifact_sha256)';

    IF artifact_constraint_name IS NULL THEN
        RAISE EXCEPTION
            'expected model_version artifact uniqueness constraint is missing'
            USING ERRCODE = '42704';
    END IF;

    EXECUTE format(
        'ALTER TABLE model_version DROP CONSTRAINT %I',
        artifact_constraint_name
    );
END;
$$;

ALTER TABLE model_version
    ADD CONSTRAINT uq_model_artifact_location
    UNIQUE (artifact_bucket, artifact_object_key);

ALTER TABLE image_object
    ADD CONSTRAINT uq_image_identity_capture UNIQUE (image_id, capture_id);

CREATE TABLE upload_session (
    upload_session_id uuid PRIMARY KEY,
    image_id uuid NOT NULL,
    capture_id uuid NOT NULL,
    station_id uuid NOT NULL,
    receipt_sha256 char(64) NOT NULL UNIQUE
        CHECK (receipt_sha256 ~ '^[0-9a-f]{64}$'),
    expected_size_bytes bigint NOT NULL CHECK (expected_size_bytes > 0),
    expected_sha256 char(64) NOT NULL
        CHECK (expected_sha256 ~ '^[0-9a-f]{64}$'),
    expected_media_type varchar(128) NOT NULL CHECK (
        expected_media_type IN ('image/png', 'image/jpeg', 'image/tiff')
    ),
    status varchar(24) NOT NULL CHECK (
        status IN ('ISSUED', 'CONFIRMED', 'EXPIRED', 'REVOKED', 'FAILED')
    ),
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    confirmed_at timestamptz,
    failure_code varchar(64),
    CONSTRAINT fk_upload_image_capture
        FOREIGN KEY (image_id, capture_id)
        REFERENCES image_object(image_id, capture_id),
    CONSTRAINT fk_upload_capture_station
        FOREIGN KEY (capture_id, station_id)
        REFERENCES capture_event(capture_id, station_id),
    CONSTRAINT ck_upload_expiry CHECK (expires_at > created_at),
    CONSTRAINT ck_upload_confirmed_at CHECK (
        (status = 'CONFIRMED' AND confirmed_at IS NOT NULL)
        OR (status <> 'CONFIRMED' AND confirmed_at IS NULL)
    )
);
CREATE UNIQUE INDEX uq_upload_one_issued_per_image
    ON upload_session(image_id)
    WHERE status = 'ISSUED';
CREATE INDEX idx_upload_session_expiry
    ON upload_session(status, expires_at)
    WHERE status = 'ISSUED';

-- 旧 CLAIMED 行没有可恢复租约，向前迁移时安全退回待重试状态。
UPDATE outbox_event
SET status = 'FAILED',
    next_attempt_at = now()
WHERE status = 'CLAIMED';
UPDATE outbox_event
SET published_at = COALESCE(published_at, now())
WHERE status = 'PUBLISHED';

ALTER TABLE outbox_event
    ADD COLUMN routing_key varchar(128) NOT NULL
        DEFAULT 'production.gpu.multitask',
    ADD COLUMN claim_owner varchar(128),
    ADD COLUMN lease_until timestamptz,
    ADD COLUMN last_error varchar(512),
    ADD CONSTRAINT ck_outbox_claim_state CHECK (
        (
            status = 'CLAIMED'
            AND claim_owner IS NOT NULL
            AND lease_until IS NOT NULL
            AND published_at IS NULL
        )
        OR (
            status = 'PUBLISHED'
            AND claim_owner IS NULL
            AND lease_until IS NULL
            AND published_at IS NOT NULL
        )
        OR (
            status IN ('NEW', 'FAILED')
            AND claim_owner IS NULL
            AND lease_until IS NULL
            AND published_at IS NULL
        )
    );
DROP INDEX idx_outbox_due;
CREATE INDEX idx_outbox_due
    ON outbox_event(status, next_attempt_at, lease_until, created_at)
    WHERE status IN ('NEW', 'FAILED', 'CLAIMED');

-- JSONB 已把 Unicode/斜杠转义规范化；对规范文本递归查找，避免仅检查
-- 顶层键时被嵌套 payload 或 \u0062ase64 一类转义绕过。
ALTER TABLE outbox_event
    DROP CONSTRAINT ck_outbox_reference_only,
    ADD CONSTRAINT ck_outbox_reference_only CHECK (
        payload::text !~* '"(base64|image_bytes)"[[:space:]]*:'
        AND position('data:image/' IN lower(payload::text)) = 0
    );

UPDATE inbox_message
SET status = 'FAILED'
WHERE status = 'PROCESSING';
UPDATE inbox_message
SET processed_at = COALESCE(processed_at, now())
WHERE status = 'PROCESSED';

ALTER TABLE inbox_message
    ADD COLUMN claim_owner varchar(128),
    ADD COLUMN lease_until timestamptz,
    ADD COLUMN attempt_count integer NOT NULL DEFAULT 0
        CHECK (attempt_count >= 0),
    ADD COLUMN last_error varchar(512),
    ADD CONSTRAINT fk_inbox_detection_task
        FOREIGN KEY (detection_task_id)
        REFERENCES detection_task(detection_task_id),
    ADD CONSTRAINT ck_inbox_claim_state CHECK (
        (
            status = 'PROCESSING'
            AND claim_owner IS NOT NULL
            AND lease_until IS NOT NULL
            AND processed_at IS NULL
        )
        OR (
            status = 'PROCESSED'
            AND claim_owner IS NULL
            AND lease_until IS NULL
            AND processed_at IS NOT NULL
        )
        OR (
            status = 'FAILED'
            AND claim_owner IS NULL
            AND lease_until IS NULL
            AND processed_at IS NULL
        )
    );
CREATE UNIQUE INDEX uq_inbox_consumer_detection_task
    ON inbox_message(consumer, detection_task_id)
    WHERE detection_task_id IS NOT NULL;
CREATE INDEX idx_inbox_recoverable
    ON inbox_message(status, lease_until)
    WHERE status IN ('PROCESSING', 'FAILED');

ALTER TABLE review_task
    ADD CONSTRAINT fk_review_task_claimed_by
        FOREIGN KEY (claimed_by) REFERENCES sys_user(user_id);

-- P2 早期草案名称迁移到 contracts/common-v1 的冻结 ReviewStatus。
ALTER TABLE review_task
    DROP CONSTRAINT review_task_status_check;
UPDATE review_task
SET status = CASE status
    WHEN 'SUBMITTED' THEN 'RESOLVED'
    WHEN 'SECOND_PENDING' THEN 'SECOND_REVIEW_PENDING'
    WHEN 'COMPLETED' THEN 'RESOLVED'
    ELSE status
END
WHERE status IN ('SUBMITTED', 'SECOND_PENDING', 'COMPLETED');
ALTER TABLE review_task
    ADD CONSTRAINT review_task_status_check CHECK (
        status IN (
            'PENDING',
            'CLAIMED',
            'SECOND_REVIEW_PENDING',
            'ESCALATED',
            'RESOLVED',
            'CANCELLED'
        )
    );
ALTER TABLE review_record
    ADD CONSTRAINT fk_review_record_reviewer
        FOREIGN KEY (reviewer_id) REFERENCES sys_user(user_id);
ALTER TABLE dataset_version
    ADD CONSTRAINT fk_dataset_version_approved_by
        FOREIGN KEY (approved_by) REFERENCES sys_user(user_id);
ALTER TABLE model_deployment
    ADD CONSTRAINT fk_model_deployment_approved_by
        FOREIGN KEY (approved_by) REFERENCES sys_user(user_id);

CREATE OR REPLACE FUNCTION td_require_record_version_increment()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.record_version <> OLD.record_version + 1 THEN
        RAISE EXCEPTION 'record_version must advance exactly once on table %', TG_TABLE_NAME
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_organization_record_version
    BEFORE UPDATE ON organization
    FOR EACH ROW EXECUTE FUNCTION td_require_record_version_increment();
CREATE TRIGGER trg_production_line_record_version
    BEFORE UPDATE ON production_line
    FOR EACH ROW EXECUTE FUNCTION td_require_record_version_increment();
CREATE TRIGGER trg_station_record_version
    BEFORE UPDATE ON station
    FOR EACH ROW EXECUTE FUNCTION td_require_record_version_increment();
CREATE TRIGGER trg_device_record_version
    BEFORE UPDATE ON device
    FOR EACH ROW EXECUTE FUNCTION td_require_record_version_increment();
CREATE TRIGGER trg_capture_event_record_version
    BEFORE UPDATE ON capture_event
    FOR EACH ROW EXECUTE FUNCTION td_require_record_version_increment();
CREATE TRIGGER trg_image_object_record_version
    BEFORE UPDATE ON image_object
    FOR EACH ROW EXECUTE FUNCTION td_require_record_version_increment();
CREATE TRIGGER trg_detection_task_record_version
    BEFORE UPDATE ON detection_task
    FOR EACH ROW EXECUTE FUNCTION td_require_record_version_increment();
CREATE TRIGGER trg_review_task_record_version
    BEFORE UPDATE ON review_task
    FOR EACH ROW EXECUTE FUNCTION td_require_record_version_increment();
CREATE TRIGGER trg_model_deployment_record_version
    BEFORE UPDATE ON model_deployment
    FOR EACH ROW EXECUTE FUNCTION td_require_record_version_increment();

CREATE OR REPLACE FUNCTION td_guard_capture_finalized()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status = 'FINALIZED' THEN
        IF NEW.status <> 'FINALIZED' THEN
            RAISE EXCEPTION 'FINALIZED capture cannot leave the terminal state'
                USING ERRCODE = '55000';
        END IF;
        -- FINALIZED 后只允许把当前处置投影指向新追加的处置事实；采集事实
        -- 本身、状态和元数据都不能原位改写。
        IF (
            to_jsonb(NEW) - ARRAY[
                'current_disposition',
                'current_disposition_id',
                'updated_at',
                'record_version'
            ]
        ) IS DISTINCT FROM (
            to_jsonb(OLD) - ARRAY[
                'current_disposition',
                'current_disposition_id',
                'updated_at',
                'record_version'
            ]
        ) THEN
            RAISE EXCEPTION 'FINALIZED capture facts are immutable'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_capture_finalized_guard
    BEFORE UPDATE ON capture_event
    FOR EACH ROW EXECUTE FUNCTION td_guard_capture_finalized();

CREATE OR REPLACE FUNCTION td_validate_detection_result_attempt()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    attempt_status varchar(24);
BEGIN
    SELECT status
    INTO attempt_status
    FROM detection_attempt
    WHERE attempt_id = NEW.accepted_attempt_id
      AND detection_task_id = NEW.detection_task_id;
    IF attempt_status IS DISTINCT FROM 'SUCCEEDED' THEN
        RAISE EXCEPTION 'accepted detection attempt must be SUCCEEDED'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_detection_result_attempt_guard
    BEFORE INSERT ON detection_result
    FOR EACH ROW EXECUTE FUNCTION td_validate_detection_result_attempt();

CREATE OR REPLACE FUNCTION td_guard_detection_attempt()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'detection attempts are append-only facts'
            USING ERRCODE = '55000';
    END IF;
    IF (
        NEW.attempt_id,
        NEW.detection_task_id,
        NEW.attempt_no,
        NEW.worker_id,
        NEW.runtime_version,
        NEW.model_sha256,
        NEW.trace_id,
        NEW.started_at,
        NEW.created_at
    ) IS DISTINCT FROM (
        OLD.attempt_id,
        OLD.detection_task_id,
        OLD.attempt_no,
        OLD.worker_id,
        OLD.runtime_version,
        OLD.model_sha256,
        OLD.trace_id,
        OLD.started_at,
        OLD.created_at
    ) THEN
        RAISE EXCEPTION 'detection attempt execution identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status IN ('SUCCEEDED', 'FAILED')
            AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
        RAISE EXCEPTION 'terminal detection attempt is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status = 'RUNNING'
            AND NEW.status NOT IN ('RUNNING', 'SUCCEEDED', 'FAILED') THEN
        RAISE EXCEPTION 'illegal detection attempt status transition: % -> %',
            OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_detection_attempt_immutable
    BEFORE UPDATE OR DELETE ON detection_attempt
    FOR EACH ROW EXECUTE FUNCTION td_guard_detection_attempt();

CREATE OR REPLACE FUNCTION td_guard_image_object()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF (
        NEW.capture_id,
        NEW.detection_task_id,
        NEW.review_record_id,
        NEW.kind,
        NEW.bucket,
        NEW.object_key,
        NEW.sha256,
        NEW.size_bytes,
        NEW.media_type,
        NEW.source_image_id
    ) IS DISTINCT FROM (
        OLD.capture_id,
        OLD.detection_task_id,
        OLD.review_record_id,
        OLD.kind,
        OLD.bucket,
        OLD.object_key,
        OLD.sha256,
        OLD.size_bytes,
        OLD.media_type,
        OLD.source_image_id
    ) THEN
        RAISE EXCEPTION 'image identity and expected content are immutable'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.state <> 'STAGING' AND (
        NEW.object_version,
        NEW.width,
        NEW.height
    ) IS DISTINCT FROM (
        OLD.object_version,
        OLD.width,
        OLD.height
    ) THEN
        RAISE EXCEPTION 'confirmed image properties are immutable'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.state = 'AVAILABLE'
            AND (NEW.width IS NULL OR NEW.height IS NULL) THEN
        RAISE EXCEPTION 'AVAILABLE image requires decoded dimensions'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.state = NEW.state THEN
        RETURN NEW;
    END IF;
    IF NOT (
        (OLD.state = 'STAGING' AND NEW.state IN (
            'AVAILABLE', 'QUARANTINED', 'ORPHANED'
        ))
        OR (OLD.state = 'AVAILABLE' AND NEW.state IN (
            'QUARANTINED', 'ARCHIVED'
        ))
        OR (OLD.state = 'ARCHIVED' AND NEW.state = 'DELETED')
    ) THEN
        RAISE EXCEPTION 'illegal image state transition: % -> %', OLD.state, NEW.state
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_image_object_state_guard
    BEFORE UPDATE ON image_object
    FOR EACH ROW EXECUTE FUNCTION td_guard_image_object();

ALTER TABLE image_object
    ADD CONSTRAINT ck_image_available_dimensions CHECK (
        state <> 'AVAILABLE' OR (width IS NOT NULL AND height IS NOT NULL)
    );

CREATE OR REPLACE FUNCTION td_require_available_image(image_id_value uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    IF image_id_value IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM image_object
                WHERE image_id = image_id_value
                  AND state = 'AVAILABLE'
            ) THEN
        RAISE EXCEPTION 'referenced image % is not AVAILABLE', image_id_value
            USING ERRCODE = '23514';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION td_guard_available_image_references()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_TABLE_NAME = 'dataset_sample' THEN
        PERFORM td_require_available_image(NEW.image_id);
        PERFORM td_require_available_image(NEW.mask_image_id);
    ELSIF TG_TABLE_NAME = 'review_record' THEN
        PERFORM td_require_available_image(NEW.annotation_image_id);
    ELSIF TG_TABLE_NAME = 'image_object' THEN
        PERFORM td_require_available_image(NEW.source_image_id);
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_dataset_sample_available_images
    BEFORE INSERT OR UPDATE OF image_id, mask_image_id ON dataset_sample
    FOR EACH ROW EXECUTE FUNCTION td_guard_available_image_references();
CREATE TRIGGER trg_review_record_available_image
    BEFORE INSERT OR UPDATE OF annotation_image_id ON review_record
    FOR EACH ROW EXECUTE FUNCTION td_guard_available_image_references();
CREATE TRIGGER trg_image_source_available
    BEFORE INSERT OR UPDATE OF source_image_id ON image_object
    FOR EACH ROW EXECUTE FUNCTION td_guard_available_image_references();

CREATE OR REPLACE FUNCTION td_guard_versioned_definition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF (to_jsonb(NEW) - 'status') IS DISTINCT FROM
            (to_jsonb(OLD) - 'status') THEN
        RAISE EXCEPTION '% definition fields are immutable', TG_TABLE_NAME
            USING ERRCODE = '55000';
    END IF;
    IF NOT (
        NEW.status = OLD.status
        OR (OLD.status = 'DRAFT' AND NEW.status IN ('APPROVED', 'RETIRED'))
        OR (OLD.status = 'APPROVED' AND NEW.status = 'RETIRED')
    ) THEN
        RAISE EXCEPTION 'illegal % status transition: % -> %',
            TG_TABLE_NAME, OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_capture_recipe_immutable
    BEFORE UPDATE ON capture_recipe
    FOR EACH ROW EXECUTE FUNCTION td_guard_versioned_definition();
CREATE TRIGGER trg_pipeline_version_immutable
    BEFORE UPDATE ON pipeline_version
    FOR EACH ROW EXECUTE FUNCTION td_guard_versioned_definition();

CREATE OR REPLACE FUNCTION td_guard_dataset_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'FROZEN' THEN
            RAISE EXCEPTION 'FROZEN dataset version is immutable'
                USING ERRCODE = '55000';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'FROZEN' THEN
        RAISE EXCEPTION 'FROZEN dataset version is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NOT (
        NEW.status = OLD.status
        OR (OLD.status = 'BUILDING' AND NEW.status IN ('VALIDATING', 'REJECTED'))
        OR (OLD.status = 'VALIDATING' AND NEW.status IN ('FROZEN', 'REJECTED'))
    ) THEN
        RAISE EXCEPTION 'illegal dataset status transition: % -> %',
            OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_dataset_version_immutable
    BEFORE UPDATE OR DELETE ON dataset_version
    FOR EACH ROW EXECUTE FUNCTION td_guard_dataset_version();

CREATE OR REPLACE FUNCTION td_guard_dataset_sample()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    old_version_status varchar(24);
    new_version_status varchar(24);
BEGIN
    -- UPDATE 必须同时保护来源和目标。否则可把 FROZEN 样本移动到
    -- BUILDING 版本，绕过不可变约束。
    IF TG_OP <> 'INSERT' THEN
        SELECT status
        INTO old_version_status
        FROM dataset_version
        WHERE dataset_version_id = OLD.dataset_version_id
        FOR SHARE;
        IF old_version_status = 'FROZEN' THEN
            RAISE EXCEPTION 'samples of a FROZEN dataset are immutable'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        SELECT status
        INTO new_version_status
        FROM dataset_version
        WHERE dataset_version_id = NEW.dataset_version_id
        FOR SHARE;
        IF new_version_status = 'FROZEN' THEN
            RAISE EXCEPTION 'samples of a FROZEN dataset are immutable'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_dataset_sample_frozen_guard
    BEFORE INSERT OR UPDATE OR DELETE ON dataset_sample
    FOR EACH ROW EXECUTE FUNCTION td_guard_dataset_sample();

CREATE OR REPLACE FUNCTION td_guard_model_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF (
        NEW.model_id,
        NEW.version,
        NEW.training_run_id,
        NEW.dataset_version_id,
        NEW.registry_name,
        NEW.registry_version,
        NEW.artifact_bucket,
        NEW.artifact_object_key,
        NEW.artifact_sha256,
        NEW.input_spec,
        NEW.output_spec
    ) IS DISTINCT FROM (
        OLD.model_id,
        OLD.version,
        OLD.training_run_id,
        OLD.dataset_version_id,
        OLD.registry_name,
        OLD.registry_version,
        OLD.artifact_bucket,
        OLD.artifact_object_key,
        OLD.artifact_sha256,
        OLD.input_spec,
        OLD.output_spec
    ) THEN
        RAISE EXCEPTION 'model version technical snapshot is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.approval_state IN ('APPROVED', 'REJECTED', 'RETIRED')
            AND NEW.evaluation_summary IS DISTINCT FROM OLD.evaluation_summary THEN
        RAISE EXCEPTION 'terminal model evaluation is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NOT (
        NEW.approval_state = OLD.approval_state
        OR (OLD.approval_state = 'CANDIDATE'
            AND NEW.approval_state IN ('VALIDATED', 'REJECTED'))
        OR (OLD.approval_state = 'VALIDATED'
            AND NEW.approval_state IN ('APPROVED', 'REJECTED'))
        OR (OLD.approval_state = 'APPROVED'
            AND NEW.approval_state = 'RETIRED')
    ) THEN
        RAISE EXCEPTION 'illegal model approval transition: % -> %',
            OLD.approval_state, NEW.approval_state
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_model_version_immutable
    BEFORE UPDATE ON model_version
    FOR EACH ROW EXECUTE FUNCTION td_guard_model_version();

CREATE OR REPLACE FUNCTION td_validate_scope_binding()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.subject_type = 'USER'
            AND NOT EXISTS (
                SELECT 1 FROM sys_user WHERE user_id = NEW.subject_id
            ) THEN
        RAISE EXCEPTION 'scope binding user does not exist'
            USING ERRCODE = '23503';
    ELSIF NEW.subject_type = 'ROLE'
            AND NOT EXISTS (
                SELECT 1 FROM sys_role WHERE role_id = NEW.subject_id
            ) THEN
        RAISE EXCEPTION 'scope binding role does not exist'
            USING ERRCODE = '23503';
    END IF;

    IF NEW.scope_type = 'ORGANIZATION'
            AND NOT EXISTS (
                SELECT 1 FROM organization
                WHERE organization_id = NEW.scope_id
            ) THEN
        RAISE EXCEPTION 'scope binding organization does not exist'
            USING ERRCODE = '23503';
    ELSIF NEW.scope_type = 'LINE'
            AND NOT EXISTS (
                SELECT 1 FROM production_line WHERE line_id = NEW.scope_id
            ) THEN
        RAISE EXCEPTION 'scope binding line does not exist'
            USING ERRCODE = '23503';
    ELSIF NEW.scope_type = 'STATION'
            AND NOT EXISTS (
                SELECT 1 FROM station WHERE station_id = NEW.scope_id
            ) THEN
        RAISE EXCEPTION 'scope binding station does not exist'
            USING ERRCODE = '23503';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER trg_scope_binding_references
    BEFORE INSERT OR UPDATE ON sys_scope_binding
    FOR EACH ROW EXECUTE FUNCTION td_validate_scope_binding();
