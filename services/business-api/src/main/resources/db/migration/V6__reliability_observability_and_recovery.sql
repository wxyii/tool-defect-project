-- P5：可靠性维护事实、人工处置审计与联合恢复演练。
-- 历史业务事实不被补偿覆盖；人工动作和恢复结果均只追加。

ALTER TABLE outbox_event
    DROP CONSTRAINT outbox_event_status_check,
    ADD CONSTRAINT outbox_event_status_check CHECK (
        status IN ('NEW', 'CLAIMED', 'PUBLISHED', 'FAILED', 'DEAD')
    ),
    DROP CONSTRAINT ck_outbox_claim_state,
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
            status IN ('NEW', 'FAILED', 'DEAD')
            AND claim_owner IS NULL
            AND lease_until IS NULL
            AND published_at IS NULL
        )
    );

CREATE TABLE reliability_issue (
    issue_id uuid PRIMARY KEY,
    issue_fingerprint char(64) NOT NULL UNIQUE
        CHECK (issue_fingerprint ~ '^[0-9a-f]{64}$'),
    issue_type varchar(64) NOT NULL CHECK (
        issue_type IN (
            'OUTBOX_DEAD',
            'QUEUE_DEAD_LETTER',
            'AVAILABLE_OBJECT_MISSING',
            'OBJECT_INTEGRITY_MISMATCH',
            'STAGING_OBJECT_ORPHANED',
            'DATABASE_UNWRITABLE',
            'MODEL_NOT_READY',
            'MONITORING_BLIND'
        )
    ),
    severity varchar(16) NOT NULL
        CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')),
    resource_type varchar(64) NOT NULL,
    resource_id varchar(256) NOT NULL,
    capture_id uuid,
    observed_state jsonb NOT NULL,
    detected_at timestamptz NOT NULL,
    request_id varchar(128) NOT NULL,
    trace_id char(32) NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_reliability_issue_capture
    ON reliability_issue(capture_id, detected_at DESC)
    WHERE capture_id IS NOT NULL;
CREATE INDEX idx_reliability_issue_type_time
    ON reliability_issue(issue_type, detected_at DESC);

CREATE TABLE maintenance_action (
    action_id uuid PRIMARY KEY,
    issue_id uuid NOT NULL REFERENCES reliability_issue(issue_id),
    action_type varchar(32) NOT NULL CHECK (
        action_type IN (
            'ACKNOWLEDGE',
            'RETRY_ORIGINAL',
            'CREATE_NEW_TASK',
            'REATTACH_OBJECT',
            'QUARANTINE_OBJECT',
            'CLOSE'
        )
    ),
    replacement_resource_id varchar(256),
    actor_id varchar(256) NOT NULL,
    actor_permissions jsonb NOT NULL,
    reason varchar(2048) NOT NULL CHECK (length(trim(reason)) >= 8),
    request_id varchar(128) NOT NULL,
    trace_id char(32) NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    occurred_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_maintenance_replacement CHECK (
        action_type <> 'CREATE_NEW_TASK'
        OR replacement_resource_id IS NOT NULL
    )
);

CREATE INDEX idx_maintenance_action_issue_time
    ON maintenance_action(issue_id, occurred_at DESC);

CREATE TABLE recovery_point (
    recovery_point_id uuid PRIMARY KEY,
    recovery_point_label varchar(128) NOT NULL UNIQUE,
    manifest_sha256 char(64) NOT NULL
        CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    component_counts jsonb NOT NULL,
    created_by varchar(256) NOT NULL,
    created_at timestamptz NOT NULL,
    request_id varchar(128) NOT NULL,
    trace_id char(32) NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$')
);

CREATE TABLE recovery_drill (
    recovery_drill_id uuid PRIMARY KEY,
    recovery_point_id uuid NOT NULL
        REFERENCES recovery_point(recovery_point_id),
    isolated_environment varchar(256) NOT NULL,
    result varchar(16) NOT NULL CHECK (result IN ('SUCCEEDED', 'FAILED')),
    verification jsonb NOT NULL,
    actor_id varchar(256) NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    request_id varchar(128) NOT NULL,
    trace_id char(32) NOT NULL CHECK (trace_id ~ '^[0-9a-f]{32}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_recovery_drill_time CHECK (finished_at >= started_at)
);

CREATE INDEX idx_recovery_drill_point_time
    ON recovery_drill(recovery_point_id, finished_at DESC);

-- 可变的技术写探针不属于业务事实，只用于证明数据库真实可写。
CREATE TABLE operational_write_probe (
    probe_key smallint PRIMARY KEY CHECK (probe_key = 1),
    probed_at timestamptz NOT NULL
);

INSERT INTO operational_write_probe(probe_key, probed_at)
VALUES (1, '-infinity'::timestamptz);

CREATE TRIGGER trg_reliability_issue_append_only
    BEFORE UPDATE OR DELETE ON reliability_issue
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();
CREATE TRIGGER trg_maintenance_action_append_only
    BEFORE UPDATE OR DELETE ON maintenance_action
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();
CREATE TRIGGER trg_recovery_point_append_only
    BEFORE UPDATE OR DELETE ON recovery_point
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();
CREATE TRIGGER trg_recovery_drill_append_only
    BEFORE UPDATE OR DELETE ON recovery_drill
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();
