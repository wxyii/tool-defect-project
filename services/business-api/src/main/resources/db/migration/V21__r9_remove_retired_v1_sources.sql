-- R9：第一版数据集/训练来源已经正式退役，且项目所有者确认无残留数据。
-- 只追加本次退役迁移；V1—V20 仍是不可回写的历史审计来源。

DO $$
DECLARE
    table_name text;
    row_count bigint;
    legacy_model_count bigint;
BEGIN
    SELECT count(*)
      INTO legacy_model_count
      FROM model_version
     WHERE source_kind = 'LEGACY_INTERNAL'
        OR training_run_id IS NOT NULL
        OR dataset_version_id IS NOT NULL;
    IF legacy_model_count <> 0 THEN
        RAISE EXCEPTION
            'R9 不能物理删除旧模型来源：发现 % 条旧模型记录；进入 HOLD',
            legacy_model_count
            USING ERRCODE = '55000';
    END IF;

    FOREACH table_name IN ARRAY ARRAY[
        'review_training_decision',
        'dataset_sample',
        'dataset_candidate_manifest',
        'training_run',
        'dataset_version',
        'dataset'
    ] LOOP
        EXECUTE format('SELECT count(*) FROM %I', table_name)
            INTO row_count;
        IF row_count <> 0 THEN
            RAISE EXCEPTION
                'R9 不能物理删除第一版表 %：发现 % 条记录；进入 HOLD',
                table_name,
                row_count
                USING ERRCODE = '55000';
        END IF;
    END LOOP;
END;
$$;

ALTER TABLE model_version
    DROP CONSTRAINT IF EXISTS ck_model_version_source_complete_exclusive,
    DROP CONSTRAINT IF EXISTS ck_model_version_source_kind;

DROP TABLE review_training_decision,
           dataset_sample,
           dataset_candidate_manifest,
           training_run,
           dataset_version,
           dataset
    CASCADE;

DROP FUNCTION IF EXISTS td_guard_review_training_sample() CASCADE;
DROP FUNCTION IF EXISTS td_guard_dataset_sample() CASCADE;
DROP FUNCTION IF EXISTS td_guard_dataset_version() CASCADE;
DROP FUNCTION IF EXISTS td_guard_candidate_manifest() CASCADE;
DROP FUNCTION IF EXISTS td_guard_training_run() CASCADE;

ALTER TABLE model_version
    DROP COLUMN training_run_id,
    DROP COLUMN dataset_version_id,
    ALTER COLUMN source_kind SET DEFAULT 'EXTERNAL_UPLOAD',
    ADD CONSTRAINT ck_model_version_source_kind
        CHECK (source_kind = 'EXTERNAL_UPLOAD'),
    ADD CONSTRAINT ck_model_version_source_complete_exclusive
        CHECK (
            model_upload_id IS NOT NULL
            AND external_source_snapshot IS NOT NULL
            AND external_source_snapshot ? 'source_system'
            AND external_source_snapshot ? 'source_version'
            AND external_source_snapshot ? 'exported_at'
            AND external_source_snapshot ? 'sha256'
            AND external_source_snapshot->>'sha256' ~ '^[0-9a-f]{64}$'
        );

DELETE FROM sys_role_permission mapping
USING sys_permission permission
WHERE mapping.permission_id = permission.permission_id
  AND permission.permission_code IN (
      'dataset:create', 'dataset:approve', 'training:create', 'training:read'
  );

DELETE FROM sys_permission
WHERE permission_code IN (
    'dataset:create', 'dataset:approve', 'training:create', 'training:read'
);

CREATE OR REPLACE FUNCTION td_guard_model_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF (
        NEW.model_id,
        NEW.version,
        NEW.source_kind,
        NEW.model_upload_id,
        NEW.external_source_snapshot,
        NEW.registry_name,
        NEW.registry_version,
        NEW.artifact_bucket,
        NEW.artifact_object_key,
        NEW.artifact_sha256,
        NEW.sbom_sha256,
        NEW.signature_key_id,
        NEW.evaluation_report_sha256,
        NEW.threshold_gate_sha256,
        NEW.input_spec,
        NEW.output_spec
    ) IS DISTINCT FROM (
        OLD.model_id,
        OLD.version,
        OLD.source_kind,
        OLD.model_upload_id,
        OLD.external_source_snapshot,
        OLD.registry_name,
        OLD.registry_version,
        OLD.artifact_bucket,
        OLD.artifact_object_key,
        OLD.artifact_sha256,
        OLD.sbom_sha256,
        OLD.signature_key_id,
        OLD.evaluation_report_sha256,
        OLD.threshold_gate_sha256,
        OLD.input_spec,
        OLD.output_spec
    ) THEN
        RAISE EXCEPTION 'model version technical and supply-chain snapshot is immutable'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.validated_by IS NOT NULL
            AND (NEW.validated_by, NEW.validated_at)
                IS DISTINCT FROM (OLD.validated_by, OLD.validated_at) THEN
        RAISE EXCEPTION 'model validation approval is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.approved_by IS NOT NULL
            AND (NEW.approved_by, NEW.approved_at)
                IS DISTINCT FROM (OLD.approved_by, OLD.approved_at) THEN
        RAISE EXCEPTION 'model release approval is immutable'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.approval_state = 'CANDIDATE'
            AND NEW.approval_state = 'VALIDATED'
            AND (NEW.validated_by IS NULL OR NEW.validated_at IS NULL) THEN
        RAISE EXCEPTION 'validated model requires an independent validation approval'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.approval_state = 'VALIDATED'
            AND NEW.approval_state = 'APPROVED'
            AND (NEW.validated_by IS NULL OR NEW.approved_by IS NULL
                OR NEW.validated_by = NEW.approved_by
                OR NEW.approved_at IS NULL) THEN
        RAISE EXCEPTION 'approved model requires two distinct approval actors'
            USING ERRCODE = '23514';
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
