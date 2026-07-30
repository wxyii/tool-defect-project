-- P2-B02：首批 PostgreSQL 业务模式。
-- 所有大文件只保存对象引用和 SHA-256，不保存二进制内容。

CREATE TABLE production_line (
    line_id uuid PRIMARY KEY,
    line_code varchar(64) NOT NULL UNIQUE,
    line_name varchar(128) NOT NULL,
    status varchar(24) NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE')),
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 0 CHECK (record_version >= 0)
);

CREATE TABLE capture_recipe (
    recipe_id uuid PRIMARY KEY,
    recipe_name varchar(128) NOT NULL,
    version varchar(64) NOT NULL,
    config jsonb NOT NULL,
    config_sha256 char(64) NOT NULL CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
    status varchar(24) NOT NULL CHECK (status IN ('DRAFT', 'APPROVED', 'RETIRED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (recipe_name, version)
);

CREATE TABLE station (
    station_id uuid PRIMARY KEY,
    line_id uuid NOT NULL REFERENCES production_line(line_id),
    station_code varchar(64) NOT NULL,
    station_name varchar(128) NOT NULL,
    timezone varchar(64) NOT NULL DEFAULT 'Asia/Shanghai',
    active_recipe_id uuid REFERENCES capture_recipe(recipe_id),
    active_pipeline_id uuid,
    status varchar(24) NOT NULL
        CHECK (status IN ('ACTIVE', 'MAINTENANCE', 'INACTIVE')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 0 CHECK (record_version >= 0),
    UNIQUE (line_id, station_code)
);

CREATE TABLE device (
    device_id uuid PRIMARY KEY,
    station_id uuid NOT NULL REFERENCES station(station_id),
    device_type varchar(32) NOT NULL
        CHECK (device_type IN ('CAMERA', 'PLC', 'IPC', 'SENSOR')),
    serial_number varchar(128),
    vendor varchar(128),
    model varchar(128),
    agent_version varchar(64),
    last_seen_at timestamptz,
    status varchar(24) NOT NULL,
    config_version varchar(64),
    certificate_fingerprint char(64)
        CHECK (certificate_fingerprint IS NULL OR certificate_fingerprint ~ '^[0-9a-f]{64}$'),
    key_reference varchar(256),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 0 CHECK (record_version >= 0)
);

CREATE UNIQUE INDEX uq_device_serial_number
    ON device(serial_number) WHERE serial_number IS NOT NULL;

CREATE TABLE capture_event (
    capture_id uuid PRIMARY KEY,
    station_id uuid NOT NULL REFERENCES station(station_id),
    trigger_id varchar(128) NOT NULL,
    client_sequence bigint NOT NULL CHECK (client_sequence >= 0),
    source_type varchar(32) NOT NULL
        CHECK (source_type IN ('ONLINE', 'MANUAL', 'HISTORICAL_IMPORT')),
    captured_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    recipe_id uuid NOT NULL REFERENCES capture_recipe(recipe_id),
    status varchar(32) NOT NULL CHECK (
        status IN (
            'CREATED', 'UPLOADING', 'READY', 'SUBMITTED',
            'PROCESSING', 'REVIEW_PENDING', 'FINALIZED', 'FAILED'
        )
    ),
    current_disposition varchar(16)
        CHECK (current_disposition IS NULL OR current_disposition IN ('PASS', 'FAIL', 'HOLD')),
    current_disposition_id uuid,
    quality_status varchar(24) NOT NULL
        CHECK (quality_status IN ('OK', 'QUALITY_WARNING', 'QUALITY_REJECTED')),
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    request_digest char(64) NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 0 CHECK (record_version >= 0),
    UNIQUE (station_id, client_sequence),
    CONSTRAINT ck_capture_finalized_disposition CHECK (
        status <> 'FINALIZED'
        OR (current_disposition_id IS NOT NULL AND current_disposition IS NOT NULL)
    )
);

CREATE TABLE image_object (
    image_id uuid PRIMARY KEY,
    capture_id uuid REFERENCES capture_event(capture_id),
    detection_task_id uuid,
    review_record_id uuid,
    kind varchar(32) NOT NULL CHECK (
        kind IN (
            'RAW', 'THUMBNAIL', 'DEFECT_MASK', 'HEATMAP',
            'OVERLAY', 'POLAR', 'REVIEW_MASK'
        )
    ),
    bucket varchar(128) NOT NULL,
    object_key varchar(1024) NOT NULL CHECK (
        object_key = lower(object_key)
        AND object_key ~ '^[a-z0-9/_\.-]+$'
    ),
    object_version varchar(256) NOT NULL DEFAULT '',
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    media_type varchar(128) NOT NULL CHECK (
        media_type IN (
            'image/png', 'image/jpeg', 'image/tiff', 'image/webp',
            'application/octet-stream', 'application/json'
        )
    ),
    width integer CHECK (width IS NULL OR width > 0),
    height integer CHECK (height IS NULL OR height > 0),
    state varchar(24) NOT NULL CHECK (
        state IN (
            'STAGING', 'AVAILABLE', 'QUARANTINED',
            'ORPHANED', 'ARCHIVED', 'DELETED'
        )
    ),
    source_image_id uuid REFERENCES image_object(image_id),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 0 CHECK (record_version >= 0),
    UNIQUE (bucket, object_key, object_version)
);

CREATE TABLE dataset (
    dataset_id uuid PRIMARY KEY,
    dataset_name varchar(128) NOT NULL UNIQUE,
    purpose varchar(128) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE dataset_version (
    dataset_version_id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES dataset(dataset_id),
    version varchar(64) NOT NULL,
    parent_version_id uuid REFERENCES dataset_version(dataset_version_id),
    manifest_bucket varchar(128),
    manifest_object_key varchar(1024),
    manifest_sha256 char(64)
        CHECK (manifest_sha256 IS NULL OR manifest_sha256 ~ '^[0-9a-f]{64}$'),
    sample_count integer NOT NULL DEFAULT 0 CHECK (sample_count >= 0),
    stratification jsonb NOT NULL DEFAULT '{}'::jsonb,
    status varchar(24) NOT NULL
        CHECK (status IN ('BUILDING', 'VALIDATING', 'FROZEN', 'REJECTED')),
    approved_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, version),
    CONSTRAINT ck_dataset_frozen_manifest CHECK (
        status <> 'FROZEN'
        OR (
            manifest_bucket IS NOT NULL
            AND manifest_object_key IS NOT NULL
            AND manifest_sha256 IS NOT NULL
        )
    )
);

CREATE TABLE training_run (
    training_run_id uuid PRIMARY KEY,
    dataset_version_id uuid NOT NULL REFERENCES dataset_version(dataset_version_id),
    status varchar(24) NOT NULL
        CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
    code_commit char(40) NOT NULL CHECK (code_commit ~ '^[0-9a-f]{40}$'),
    config jsonb NOT NULL,
    config_sha256 char(64) NOT NULL CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
    environment_lock_sha256 char(64) NOT NULL
        CHECK (environment_lock_sha256 ~ '^[0-9a-f]{64}$'),
    random_seed bigint NOT NULL,
    registry_run_uri varchar(1024),
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE model (
    model_id uuid PRIMARY KEY,
    model_name varchar(128) NOT NULL UNIQUE,
    task_type varchar(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE model_version (
    model_version_id uuid PRIMARY KEY,
    model_id uuid NOT NULL REFERENCES model(model_id),
    version varchar(64) NOT NULL,
    training_run_id uuid REFERENCES training_run(training_run_id),
    dataset_version_id uuid NOT NULL REFERENCES dataset_version(dataset_version_id),
    registry_name varchar(256),
    registry_version varchar(128),
    artifact_bucket varchar(128) NOT NULL,
    artifact_object_key varchar(1024) NOT NULL,
    artifact_sha256 char(64) NOT NULL CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    input_spec jsonb NOT NULL,
    output_spec jsonb NOT NULL,
    evaluation_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    approval_state varchar(24) NOT NULL CHECK (
        approval_state IN ('CANDIDATE', 'VALIDATED', 'APPROVED', 'REJECTED', 'RETIRED')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (model_id, version),
    UNIQUE (artifact_bucket, artifact_object_key, artifact_sha256)
);

CREATE TABLE pipeline_version (
    pipeline_id uuid PRIMARY KEY,
    pipeline_name varchar(128) NOT NULL,
    version varchar(64) NOT NULL,
    preprocessor_id varchar(128) NOT NULL,
    preprocessor_version varchar(128) NOT NULL,
    algorithm_id varchar(128) NOT NULL,
    algorithm_version varchar(128) NOT NULL,
    model_version_id uuid NOT NULL REFERENCES model_version(model_version_id),
    config jsonb NOT NULL,
    config_sha256 char(64) NOT NULL CHECK (config_sha256 ~ '^[0-9a-f]{64}$'),
    status varchar(24) NOT NULL CHECK (status IN ('DRAFT', 'APPROVED', 'RETIRED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (pipeline_name, version)
);

ALTER TABLE station
    ADD CONSTRAINT fk_station_active_pipeline
    FOREIGN KEY (active_pipeline_id) REFERENCES pipeline_version(pipeline_id);

CREATE TABLE detection_task (
    detection_task_id uuid PRIMARY KEY,
    capture_id uuid NOT NULL REFERENCES capture_event(capture_id),
    pipeline_id uuid NOT NULL REFERENCES pipeline_version(pipeline_id),
    purpose varchar(24) NOT NULL
        CHECK (purpose IN ('PRODUCTION', 'SHADOW', 'AUTHORIZED_RERUN', 'BATCH')),
    status varchar(24) NOT NULL CHECK (
        status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'RETRY_WAIT', 'DEAD')
    ),
    priority smallint NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_retry_at timestamptz,
    queued_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    last_error_code varchar(64),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 0 CHECK (record_version >= 0),
    UNIQUE (capture_id, pipeline_id, purpose)
);

CREATE TABLE detection_attempt (
    attempt_id uuid PRIMARY KEY,
    detection_task_id uuid NOT NULL REFERENCES detection_task(detection_task_id),
    attempt_no integer NOT NULL CHECK (attempt_no > 0),
    worker_id varchar(128) NOT NULL,
    runtime_version varchar(128) NOT NULL,
    model_sha256 char(64) NOT NULL CHECK (model_sha256 ~ '^[0-9a-f]{64}$'),
    trace_id char(32) NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    status varchar(24) NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    timings jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code varchar(64),
    error_message varchar(512),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (detection_task_id, attempt_no)
);

CREATE TABLE detection_result (
    detection_result_id uuid PRIMARY KEY,
    detection_task_id uuid NOT NULL UNIQUE REFERENCES detection_task(detection_task_id),
    accepted_attempt_id uuid NOT NULL UNIQUE REFERENCES detection_attempt(attempt_id),
    schema_version varchar(16) NOT NULL CHECK (length(trim(schema_version)) > 0),
    algorithm_outcome varchar(24) NOT NULL
        CHECK (algorithm_outcome IN ('QUALIFIED', 'UNQUALIFIED', 'INCONCLUSIVE')),
    confidence numeric(10,9) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    qualified_probability numeric(10,9)
        CHECK (qualified_probability IS NULL OR qualified_probability BETWEEN 0 AND 1),
    unqualified_probability numeric(10,9)
        CHECK (unqualified_probability IS NULL OR unqualified_probability BETWEEN 0 AND 1),
    preprocess_quality varchar(24) NOT NULL
        CHECK (preprocess_quality IN ('OK', 'WARNING', 'REJECTED')),
    region_count integer NOT NULL DEFAULT 0 CHECK (region_count >= 0),
    warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    standard_result jsonb NOT NULL,
    result_sha256 char(64) NOT NULL CHECK (result_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_detection_probability_pair CHECK (
        (qualified_probability IS NULL AND unqualified_probability IS NULL)
        OR (
            qualified_probability IS NOT NULL
            AND unqualified_probability IS NOT NULL
            AND abs((qualified_probability + unqualified_probability) - 1.0) <= 0.000001
        )
    )
);

CREATE TABLE defect_region (
    region_id uuid PRIMARY KEY,
    detection_result_id uuid NOT NULL REFERENCES detection_result(detection_result_id),
    region_no integer NOT NULL CHECK (region_no >= 0),
    coordinate_space varchar(32) NOT NULL,
    geometry_type varchar(32) NOT NULL
        CHECK (geometry_type IN ('MASK_REF', 'POLYGON', 'BBOX', 'POLAR_INTERVAL')),
    geometry jsonb NOT NULL,
    peak_score numeric CHECK (peak_score IS NULL OR peak_score BETWEEN 0 AND 1),
    mean_score numeric CHECK (mean_score IS NULL OR mean_score BETWEEN 0 AND 1),
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (detection_result_id, region_no)
);

CREATE TABLE review_task (
    review_task_id uuid PRIMARY KEY,
    capture_id uuid NOT NULL REFERENCES capture_event(capture_id),
    priority smallint NOT NULL,
    status varchar(24) NOT NULL CHECK (
        status IN (
            'PENDING', 'CLAIMED', 'SUBMITTED',
            'SECOND_PENDING', 'COMPLETED', 'CANCELLED'
        )
    ),
    pool_scope jsonb NOT NULL DEFAULT '{}'::jsonb,
    trigger_reasons jsonb NOT NULL,
    claimed_by uuid,
    lease_expires_at timestamptz,
    requires_second_review boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 0 CHECK (record_version >= 0)
);

CREATE TABLE review_record (
    review_record_id uuid PRIMARY KEY,
    review_task_id uuid NOT NULL REFERENCES review_task(review_task_id),
    reviewer_id uuid NOT NULL,
    decision varchar(16) NOT NULL CHECK (decision IN ('PASS', 'FAIL', 'HOLD')),
    reason_code varchar(64) NOT NULL,
    comment varchar(2048),
    annotation_image_id uuid,
    defect_type_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
    review_round integer NOT NULL CHECK (review_round > 0),
    independent_review_group uuid,
    supersedes_id uuid REFERENCES review_record(review_record_id),
    submitted_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (review_task_id, reviewer_id, review_round)
);

CREATE TABLE disposition_record (
    disposition_id uuid PRIMARY KEY,
    capture_id uuid NOT NULL REFERENCES capture_event(capture_id),
    source varchar(24) NOT NULL
        CHECK (source IN ('AUTO', 'REVIEW', 'SUPERVISOR_OVERRIDE')),
    disposition varchar(16) NOT NULL CHECK (disposition IN ('PASS', 'FAIL', 'HOLD')),
    policy_version varchar(64),
    review_record_id uuid REFERENCES review_record(review_record_id),
    reason_code varchar(64) NOT NULL,
    actor_id uuid,
    supersedes_id uuid REFERENCES disposition_record(disposition_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_disposition_source_reference CHECK (
        (source = 'AUTO' AND policy_version IS NOT NULL)
        OR (source <> 'AUTO' AND review_record_id IS NOT NULL)
    )
);

ALTER TABLE capture_event
    ADD CONSTRAINT fk_capture_current_disposition
    FOREIGN KEY (current_disposition_id) REFERENCES disposition_record(disposition_id);

ALTER TABLE image_object
    ADD CONSTRAINT fk_image_detection_task
    FOREIGN KEY (detection_task_id) REFERENCES detection_task(detection_task_id);

ALTER TABLE image_object
    ADD CONSTRAINT fk_image_review_record
    FOREIGN KEY (review_record_id) REFERENCES review_record(review_record_id);

ALTER TABLE review_record
    ADD CONSTRAINT fk_review_annotation_image
    FOREIGN KEY (annotation_image_id) REFERENCES image_object(image_id);

CREATE TABLE dataset_sample (
    dataset_sample_id uuid PRIMARY KEY,
    dataset_version_id uuid NOT NULL REFERENCES dataset_version(dataset_version_id),
    sample_key varchar(256) NOT NULL,
    capture_id uuid REFERENCES capture_event(capture_id),
    historical_sample_id varchar(256),
    image_id uuid NOT NULL REFERENCES image_object(image_id),
    label varchar(64) NOT NULL,
    mask_image_id uuid REFERENCES image_object(image_id),
    split varchar(16) NOT NULL CHECK (split IN ('TRAIN', 'VALIDATION', 'TEST')),
    source_review_record_id uuid REFERENCES review_record(review_record_id),
    content_sha256 char(64) NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    group_key varchar(256) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (dataset_version_id, sample_key),
    CONSTRAINT ck_dataset_sample_source CHECK (
        capture_id IS NOT NULL OR historical_sample_id IS NOT NULL
    )
);

CREATE TABLE model_deployment (
    model_deployment_id uuid PRIMARY KEY,
    model_version_id uuid NOT NULL REFERENCES model_version(model_version_id),
    environment varchar(32) NOT NULL,
    station_scope jsonb NOT NULL,
    traffic_ratio numeric(6,5) NOT NULL CHECK (traffic_ratio BETWEEN 0 AND 1),
    effective_at timestamptz,
    approved_by uuid,
    rollback_target_id uuid REFERENCES model_deployment(model_deployment_id),
    status varchar(24) NOT NULL CHECK (
        status IN ('REQUESTED', 'APPROVED', 'ACTIVE', 'ROLLED_BACK', 'REJECTED')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    record_version bigint NOT NULL DEFAULT 0 CHECK (record_version >= 0)
);

CREATE TABLE sys_user (
    user_id uuid PRIMARY KEY,
    external_subject varchar(256) NOT NULL UNIQUE,
    display_name varchar(256) NOT NULL,
    status varchar(24) NOT NULL CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sys_role (
    role_id uuid PRIMARY KEY,
    role_code varchar(64) NOT NULL UNIQUE,
    role_name varchar(128) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sys_permission (
    permission_id uuid PRIMARY KEY,
    permission_code varchar(128) NOT NULL UNIQUE,
    description varchar(512) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sys_user_role (
    user_id uuid NOT NULL REFERENCES sys_user(user_id),
    role_id uuid NOT NULL REFERENCES sys_role(role_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE sys_role_permission (
    role_id uuid NOT NULL REFERENCES sys_role(role_id),
    permission_id uuid NOT NULL REFERENCES sys_permission(permission_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE sys_scope_binding (
    scope_binding_id uuid PRIMARY KEY,
    subject_type varchar(16) NOT NULL CHECK (subject_type IN ('USER', 'ROLE')),
    subject_id uuid NOT NULL,
    scope_type varchar(16) NOT NULL CHECK (scope_type IN ('ORGANIZATION', 'LINE', 'STATION')),
    scope_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (subject_type, subject_id, scope_type, scope_id)
);

CREATE TABLE audit_log (
    audit_id uuid PRIMARY KEY,
    occurred_at timestamptz NOT NULL,
    actor_type varchar(24) NOT NULL,
    actor_id varchar(256) NOT NULL,
    actor_ip inet,
    action varchar(128) NOT NULL,
    resource_type varchar(128) NOT NULL,
    resource_id varchar(256) NOT NULL,
    before_digest char(64)
        CHECK (before_digest IS NULL OR before_digest ~ '^[0-9a-f]{64}$'),
    after_digest char(64)
        CHECK (after_digest IS NULL OR after_digest ~ '^[0-9a-f]{64}$'),
    reason varchar(2048),
    request_id varchar(128) NOT NULL,
    trace_id char(32) NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    result varchar(24) NOT NULL,
    error_code varchar(64),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE outbox_event (
    event_id uuid PRIMARY KEY,
    aggregate_type varchar(128) NOT NULL,
    aggregate_id uuid NOT NULL,
    event_type varchar(128) NOT NULL CHECK (event_type ~ '\.v[0-9]+$'),
    payload jsonb NOT NULL,
    status varchar(24) NOT NULL
        CHECK (status IN ('NEW', 'CLAIMED', 'PUBLISHED', 'FAILED')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    CONSTRAINT ck_outbox_reference_only CHECK (
        NOT (payload ? 'base64')
        AND NOT (payload ? 'image_bytes')
    )
);

CREATE TABLE inbox_message (
    message_id varchar(128) NOT NULL,
    consumer varchar(128) NOT NULL,
    detection_task_id uuid,
    status varchar(24) NOT NULL CHECK (status IN ('PROCESSING', 'PROCESSED', 'FAILED')),
    result_sha256 char(64)
        CHECK (result_sha256 IS NULL OR result_sha256 ~ '^[0-9a-f]{64}$'),
    received_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    PRIMARY KEY (message_id, consumer)
);

CREATE INDEX idx_capture_station_time
    ON capture_event(station_id, captured_at DESC);
CREATE INDEX idx_capture_status_time
    ON capture_event(status, captured_at);
CREATE INDEX idx_capture_disposition_time
    ON capture_event(current_disposition, captured_at);
CREATE INDEX idx_detection_task_queue
    ON detection_task(status, priority, queued_at);
CREATE INDEX idx_review_task_queue
    ON review_task(status, priority, created_at);
CREATE INDEX idx_review_task_lease
    ON review_task(claimed_by, lease_expires_at);
CREATE INDEX idx_image_capture_kind
    ON image_object(capture_id, kind);
CREATE INDEX idx_model_deployment_active
    ON model_deployment(environment, status, effective_at);
CREATE INDEX idx_outbox_due
    ON outbox_event(status, next_attempt_at)
    WHERE status IN ('NEW', 'FAILED');
