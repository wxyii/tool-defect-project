-- P3-01/P3-02/P3-04：自动检测纵向闭环所需的幂等、消息关联和策略审计事实。
-- 所有新增结构均为向前兼容；历史记录不被回填为猜测值。

CREATE TABLE idempotency_record (
    operation varchar(128) NOT NULL,
    actor_id varchar(256) NOT NULL,
    idempotency_key varchar(256) NOT NULL,
    request_sha256 char(64) NOT NULL
        CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    response_status integer NOT NULL CHECK (response_status BETWEEN 200 AND 599),
    response_body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (operation, actor_id, idempotency_key)
);

CREATE INDEX idx_idempotency_created_at
    ON idempotency_record(created_at);

ALTER TABLE device
    ADD COLUMN heartbeat_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE detection_attempt
    ADD COLUMN source_message_id varchar(128),
    ADD COLUMN callback_sha256 char(64)
        CHECK (callback_sha256 IS NULL OR callback_sha256 ~ '^[0-9a-f]{64}$');

CREATE UNIQUE INDEX uq_detection_attempt_source_message
    ON detection_attempt(source_message_id)
    WHERE source_message_id IS NOT NULL;

ALTER TABLE disposition_record
    ADD COLUMN policy_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN input_summary_sha256 char(64)
        CHECK (
            input_summary_sha256 IS NULL
            OR input_summary_sha256 ~ '^[0-9a-f]{64}$'
        );

-- 历史 AUTO 记录没有可安全推断的阈值和输入摘要，因此不伪造回填；
-- 新记录必须满足该约束，历史数据在后续受控治理中单独处理。
ALTER TABLE disposition_record
    ADD CONSTRAINT ck_auto_disposition_policy_evidence CHECK (
        source <> 'AUTO'
        OR (
            input_summary_sha256 IS NOT NULL
            AND jsonb_typeof(policy_snapshot) = 'object'
            AND policy_snapshot <> '{}'::jsonb
        )
    ) NOT VALID;

CREATE UNIQUE INDEX uq_review_task_active_capture
    ON review_task(capture_id)
    WHERE status IN (
        'PENDING',
        'CLAIMED',
        'SECOND_REVIEW_PENDING',
        'ESCALATED'
    );

CREATE OR REPLACE FUNCTION td_guard_detection_attempt_p3_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.source_message_id IS DISTINCT FROM OLD.source_message_id THEN
        RAISE EXCEPTION 'detection attempt source message is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.callback_sha256 IS NOT NULL
            AND NEW.callback_sha256 IS DISTINCT FROM OLD.callback_sha256 THEN
        RAISE EXCEPTION 'detection attempt callback hash is immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_detection_attempt_p3_identity
    BEFORE UPDATE ON detection_attempt
    FOR EACH ROW EXECUTE FUNCTION td_guard_detection_attempt_p3_identity();
