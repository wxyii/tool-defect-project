-- P6-02：候选清单必须先在业务库登记并完成独立质量审批，数据集版本只引用
-- 已登记的不可变对象。历史 dataset_version 行保留为空，不能被猜测回填。

CREATE TABLE dataset_candidate_manifest (
    candidate_manifest_id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES dataset(dataset_id),
    manifest_bucket varchar(128) NOT NULL,
    manifest_object_key varchar(1024) NOT NULL,
    manifest_sha256 char(64) NOT NULL
        CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    sample_count integer NOT NULL CHECK (sample_count >= 0),
    approval_state varchar(24) NOT NULL
        CHECK (approval_state IN ('REGISTERED', 'APPROVED', 'REJECTED')),
    approved_by uuid REFERENCES sys_user(user_id),
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_dataset_candidate_manifest_object
        UNIQUE (manifest_bucket, manifest_object_key, manifest_sha256),
    CONSTRAINT ck_candidate_manifest_approval_audit CHECK (
        (approval_state = 'APPROVED' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
        OR (approval_state IN ('REGISTERED', 'REJECTED')
            AND approved_by IS NULL AND approved_at IS NULL)
    )
);

ALTER TABLE dataset_version
    ADD COLUMN candidate_manifest_id uuid,
    ADD COLUMN purpose varchar(256),
    ADD COLUMN record_version bigint NOT NULL DEFAULT 0
        CHECK (record_version >= 0),
    ADD CONSTRAINT fk_dataset_version_candidate_manifest
        FOREIGN KEY (candidate_manifest_id)
        REFERENCES dataset_candidate_manifest(candidate_manifest_id),
    ADD CONSTRAINT ck_dataset_version_purpose
        CHECK (purpose IS NULL OR length(trim(purpose)) BETWEEN 1 AND 256);

CREATE INDEX idx_dataset_candidate_manifest_dataset_state
    ON dataset_candidate_manifest(dataset_id, approval_state, created_at DESC);

CREATE OR REPLACE FUNCTION td_guard_candidate_manifest()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.approval_state = 'APPROVED' THEN
        IF ROW(NEW.dataset_id, NEW.manifest_bucket, NEW.manifest_object_key,
               NEW.manifest_sha256, NEW.sample_count)
            IS DISTINCT FROM ROW(OLD.dataset_id, OLD.manifest_bucket,
               OLD.manifest_object_key, OLD.manifest_sha256, OLD.sample_count) THEN
            RAISE EXCEPTION 'APPROVED candidate manifest is immutable'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    IF NOT (
        NEW.approval_state = OLD.approval_state
        OR (OLD.approval_state = 'REGISTERED'
            AND NEW.approval_state IN ('APPROVED', 'REJECTED'))
    ) THEN
        RAISE EXCEPTION 'illegal candidate manifest approval transition: % -> %',
            OLD.approval_state, NEW.approval_state
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_candidate_manifest_immutable
    BEFORE UPDATE ON dataset_candidate_manifest
    FOR EACH ROW EXECUTE FUNCTION td_guard_candidate_manifest();

-- V3 为其他不可变业务事实建立了 record_version 触发器，但遗漏了 dataset_version。
-- 新的应用层乐观并发更新必须和数据库一致，不能只靠 WHERE 条件。
CREATE TRIGGER trg_dataset_version_record_version
    BEFORE UPDATE ON dataset_version
    FOR EACH ROW EXECUTE FUNCTION td_require_record_version_increment();
