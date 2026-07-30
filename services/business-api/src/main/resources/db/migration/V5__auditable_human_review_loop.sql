-- P4-01/P4-02/P4-03/P4-05：可审计人工复核、标注和训练准入。
-- 历史记录不回填为猜测值；新增约束对所有新写入立即生效。

CREATE TABLE review_reason_code (
    reason_code varchar(64) PRIMARY KEY,
    display_name varchar(128) NOT NULL,
    active boolean NOT NULL DEFAULT true,
    requires_comment boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    disabled_at timestamptz,
    CONSTRAINT ck_review_reason_code_state CHECK (
        (active AND disabled_at IS NULL)
        OR (NOT active AND disabled_at IS NOT NULL)
    )
);

INSERT INTO review_reason_code(
    reason_code,
    display_name,
    requires_comment
) VALUES
    ('MODEL_FALSE_POSITIVE', '模型误报', false),
    ('MODEL_FALSE_NEGATIVE', '模型漏检', false),
    ('MASK_INACCURATE', '模型掩膜不准确', false),
    ('IMAGE_QUALITY', '图片质量问题', false),
    ('PREPROCESS_FAILURE', '预处理失败', false),
    ('DEVICE_OR_PROCESS', '设备或工艺异常', false),
    ('STANDARD_AMBIGUOUS', '判定标准有争议', true),
    ('CONFIRMED_CORRECT', '抽检确认算法正确', false),
    ('OTHER', '其他', true);

ALTER TABLE review_task
    ADD COLUMN claimed_from_status varchar(24),
    ADD COLUMN revision_of_task_id uuid,
    ADD COLUMN supersedes_review_record_id uuid;

ALTER TABLE review_task
    ADD CONSTRAINT fk_review_task_revision
        FOREIGN KEY (revision_of_task_id) REFERENCES review_task(review_task_id),
    ADD CONSTRAINT fk_review_task_superseded_record
        FOREIGN KEY (supersedes_review_record_id)
        REFERENCES review_record(review_record_id),
    ADD CONSTRAINT ck_review_task_not_self_revision CHECK (
        revision_of_task_id IS NULL
        OR revision_of_task_id <> review_task_id
    ),
    ADD CONSTRAINT ck_review_task_priority CHECK (
        priority IN (0, 10, 20, 30)
    ) NOT VALID,
    ADD CONSTRAINT ck_review_task_claim_source CHECK (
        claimed_from_status IS NULL
        OR claimed_from_status IN (
            'PENDING',
            'SECOND_REVIEW_PENDING',
            'ESCALATED'
        )
    ) NOT VALID,
    ADD CONSTRAINT ck_review_task_claim_fields CHECK (
        status <> 'CLAIMED'
        OR (
            claimed_by IS NOT NULL
            AND lease_expires_at IS NOT NULL
            AND claimed_from_status IS NOT NULL
        )
    ) NOT VALID;

ALTER TABLE review_record
    ADD COLUMN client_submitted_at timestamptz,
    ADD COLUMN submission_sha256 char(64),
    ADD COLUMN adjudication boolean NOT NULL DEFAULT false,
    ADD CONSTRAINT ck_review_submission_sha256 CHECK (
        submission_sha256 IS NULL
        OR submission_sha256 ~ '^[0-9a-f]{64}$'
    );

ALTER TABLE image_object
    ADD COLUMN review_task_id uuid,
    ADD CONSTRAINT fk_image_review_task
        FOREIGN KEY (review_task_id) REFERENCES review_task(review_task_id),
    ADD CONSTRAINT ck_review_mask_task_binding CHECK (
        kind <> 'REVIEW_MASK' OR review_task_id IS NOT NULL
    ) NOT VALID;

CREATE INDEX idx_review_task_revision
    ON review_task(revision_of_task_id)
    WHERE revision_of_task_id IS NOT NULL;

CREATE INDEX idx_review_record_revision
    ON review_record(supersedes_id)
    WHERE supersedes_id IS NOT NULL;

CREATE INDEX idx_review_mask_task
    ON image_object(review_task_id, created_at)
    WHERE kind = 'REVIEW_MASK';

CREATE TABLE review_training_decision (
    training_decision_id uuid PRIMARY KEY,
    review_record_id uuid NOT NULL REFERENCES review_record(review_record_id),
    decision varchar(16) NOT NULL
        CHECK (decision IN ('APPROVED', 'REJECTED')),
    decided_by uuid NOT NULL REFERENCES sys_user(user_id),
    reason varchar(2048) NOT NULL CHECK (length(trim(reason)) > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_review_training_decision_latest
    ON review_training_decision(review_record_id, created_at DESC);

CREATE TRIGGER trg_review_training_decision_append_only
    BEFORE UPDATE OR DELETE ON review_training_decision
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

CREATE OR REPLACE FUNCTION td_guard_review_record_p4()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    reason_active boolean;
    reason_requires_comment boolean;
    annotation_kind varchar(32);
    annotation_task_id uuid;
BEGIN
    SELECT active, requires_comment
      INTO reason_active, reason_requires_comment
      FROM review_reason_code
     WHERE reason_code = NEW.reason_code;

    IF reason_active IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'review reason code is missing or inactive'
            USING ERRCODE = '23514';
    END IF;
    IF reason_requires_comment
            AND length(trim(COALESCE(NEW.comment, ''))) = 0 THEN
        RAISE EXCEPTION 'review reason code requires a comment'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.annotation_image_id IS NOT NULL THEN
        SELECT kind, review_task_id
          INTO annotation_kind, annotation_task_id
          FROM image_object
         WHERE image_id = NEW.annotation_image_id
           AND state = 'AVAILABLE';
        IF annotation_kind IS DISTINCT FROM 'REVIEW_MASK'
                OR annotation_task_id IS DISTINCT FROM NEW.review_task_id THEN
            RAISE EXCEPTION 'annotation must be an AVAILABLE review mask for this task'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_review_record_p4
    BEFORE INSERT ON review_record
    FOR EACH ROW EXECUTE FUNCTION td_guard_review_record_p4();

CREATE OR REPLACE FUNCTION td_guard_review_training_sample()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    latest_decision varchar(16);
    source_decision varchar(16);
    source_task_status varchar(24);
BEGIN
    IF NEW.source_review_record_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT record.decision, task.status
      INTO source_decision, source_task_status
      FROM review_record record
      JOIN review_task task
        ON task.review_task_id = record.review_task_id
     WHERE record.review_record_id = NEW.source_review_record_id;

    SELECT decision
      INTO latest_decision
      FROM review_training_decision
     WHERE review_record_id = NEW.source_review_record_id
     ORDER BY created_at DESC, training_decision_id DESC
     LIMIT 1;

    IF source_task_status IS DISTINCT FROM 'RESOLVED'
            OR source_decision NOT IN ('PASS', 'FAIL')
            OR latest_decision IS DISTINCT FROM 'APPROVED' THEN
        RAISE EXCEPTION 'review sample lacks resolved quality approval'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_dataset_sample_review_training_approval
    BEFORE INSERT OR UPDATE OF source_review_record_id ON dataset_sample
    FOR EACH ROW EXECUTE FUNCTION td_guard_review_training_sample();
