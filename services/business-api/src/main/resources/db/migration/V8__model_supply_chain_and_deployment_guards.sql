-- P6-05/P6-06：模型供应链证据、独立审批和发布状态保护。
-- 历史记录不回填为猜测值；新登记/部署由应用层强制填写全部证据。

ALTER TABLE model_version
    ADD COLUMN registered_by uuid,
    ADD COLUMN sbom_sha256 char(64),
    ADD COLUMN signature_key_id varchar(256),
    ADD COLUMN evaluation_report_sha256 char(64),
    ADD COLUMN threshold_gate_sha256 char(64),
    ADD COLUMN validated_by uuid,
    ADD COLUMN validated_at timestamptz,
    ADD COLUMN approved_by uuid,
    ADD COLUMN approved_at timestamptz,
    ADD CONSTRAINT fk_model_version_registered_by
        FOREIGN KEY (registered_by) REFERENCES sys_user(user_id),
    ADD CONSTRAINT fk_model_version_validated_by
        FOREIGN KEY (validated_by) REFERENCES sys_user(user_id),
    ADD CONSTRAINT fk_model_version_approved_by
        FOREIGN KEY (approved_by) REFERENCES sys_user(user_id),
    ADD CONSTRAINT ck_model_version_sbom_sha256
        CHECK (sbom_sha256 IS NULL OR sbom_sha256 ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT ck_model_version_evaluation_report_sha256
        CHECK (evaluation_report_sha256 IS NULL
            OR evaluation_report_sha256 ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT ck_model_version_threshold_gate_sha256
        CHECK (threshold_gate_sha256 IS NULL
            OR threshold_gate_sha256 ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT ck_model_version_signature_key
        CHECK (signature_key_id IS NULL OR length(trim(signature_key_id)) > 0),
    ADD CONSTRAINT ck_model_version_validation_audit
        CHECK ((validated_by IS NULL AND validated_at IS NULL)
            OR (validated_by IS NOT NULL AND validated_at IS NOT NULL)),
    ADD CONSTRAINT ck_model_version_approval_audit
        CHECK ((approved_by IS NULL AND approved_at IS NULL)
            OR (approved_by IS NOT NULL AND approved_at IS NOT NULL));

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
        NEW.sbom_sha256,
        NEW.signature_key_id,
        NEW.evaluation_report_sha256,
        NEW.threshold_gate_sha256,
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

CREATE TABLE model_version_approval (
    approval_id uuid PRIMARY KEY,
    model_version_id uuid NOT NULL REFERENCES model_version(model_version_id),
    stage varchar(16) NOT NULL CHECK (stage IN ('VALIDATION', 'RELEASE')),
    decision varchar(16) NOT NULL CHECK (decision IN ('APPROVE', 'REJECT')),
    actor_id uuid NOT NULL REFERENCES sys_user(user_id),
    reason varchar(2000) NOT NULL CHECK (length(trim(reason)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (model_version_id, stage)
);

CREATE OR REPLACE FUNCTION td_guard_model_version_approval()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    registered uuid;
    validated uuid;
BEGIN
    SELECT registered_by, validated_by INTO registered, validated
    FROM model_version
    WHERE model_version_id = NEW.model_version_id;
    IF registered IS NULL OR registered = NEW.actor_id THEN
        RAISE EXCEPTION 'model registrar cannot approve its own version'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.stage = 'RELEASE' AND validated = NEW.actor_id THEN
        RAISE EXCEPTION 'validation and release approvals must be independent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_model_version_approval_guard
    BEFORE INSERT ON model_version_approval
    FOR EACH ROW EXECUTE FUNCTION td_guard_model_version_approval();

ALTER TABLE model_deployment
    ADD COLUMN deployment_strategy varchar(32) NOT NULL DEFAULT 'PERCENTAGE',
    ADD COLUMN requested_by uuid,
    ADD COLUMN rollback_model_version_id uuid,
    ADD COLUMN quality_approved_by uuid,
    ADD COLUMN release_approved_by uuid,
    ADD COLUMN quality_approved_at timestamptz,
    ADD COLUMN release_approved_at timestamptz,
    ADD COLUMN quality_approval_reason varchar(2000),
    ADD COLUMN release_approval_reason varchar(2000),
    ADD COLUMN warmup_evidence_sha256 char(64),
    ADD COLUMN metrics_gate_sha256 char(64),
    ADD CONSTRAINT fk_model_deployment_requested_by
        FOREIGN KEY (requested_by) REFERENCES sys_user(user_id),
    ADD CONSTRAINT fk_model_deployment_quality_approved_by
        FOREIGN KEY (quality_approved_by) REFERENCES sys_user(user_id),
    ADD CONSTRAINT fk_model_deployment_release_approved_by
        FOREIGN KEY (release_approved_by) REFERENCES sys_user(user_id),
    ADD CONSTRAINT fk_model_deployment_rollback_model_version
        FOREIGN KEY (rollback_model_version_id) REFERENCES model_version(model_version_id),
    ADD CONSTRAINT ck_model_deployment_strategy
        CHECK (deployment_strategy IN ('STATION', 'PERCENTAGE')),
    ADD CONSTRAINT ck_model_deployment_environment
        CHECK (environment IN ('SHADOW', 'CANARY', 'PRODUCTION')),
    ADD CONSTRAINT ck_model_deployment_station_scope
        CHECK (deployment_strategy <> 'STATION' OR jsonb_array_length(station_scope) > 0),
    ADD CONSTRAINT ck_model_deployment_shadow_traffic
        CHECK (environment <> 'SHADOW' OR traffic_ratio = 0),
    ADD CONSTRAINT ck_model_deployment_warmup_hash
        CHECK (warmup_evidence_sha256 IS NULL OR warmup_evidence_sha256 ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT ck_model_deployment_metrics_hash
        CHECK (metrics_gate_sha256 IS NULL OR metrics_gate_sha256 ~ '^[0-9a-f]{64}$');

CREATE TABLE model_deployment_approval (
    approval_id uuid PRIMARY KEY,
    model_deployment_id uuid NOT NULL REFERENCES model_deployment(model_deployment_id),
    role varchar(32) NOT NULL CHECK (role IN ('QUALITY_APPROVER', 'MODEL_RELEASE_APPROVER')),
    decision varchar(16) NOT NULL CHECK (decision IN ('APPROVE', 'REJECT')),
    actor_id uuid NOT NULL REFERENCES sys_user(user_id),
    reason varchar(2000) NOT NULL CHECK (length(trim(reason)) > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (model_deployment_id, role)
);

CREATE OR REPLACE FUNCTION td_guard_model_deployment()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF (
        NEW.model_version_id,
        NEW.environment,
        NEW.deployment_strategy,
        NEW.station_scope,
        NEW.traffic_ratio,
        NEW.requested_by,
        NEW.rollback_model_version_id
    ) IS DISTINCT FROM (
        OLD.model_version_id,
        OLD.environment,
        OLD.deployment_strategy,
        OLD.station_scope,
        OLD.traffic_ratio,
        OLD.requested_by,
        OLD.rollback_model_version_id
    ) THEN
        RAISE EXCEPTION 'model deployment target and scope are immutable'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.status = 'REQUESTED'
            AND NEW.status NOT IN ('REQUESTED', 'APPROVED', 'REJECTED') THEN
        RAISE EXCEPTION 'illegal deployment transition: % -> %', OLD.status, NEW.status
            USING ERRCODE = '23514';
    ELSIF OLD.status = 'APPROVED' AND NEW.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'approved deployment can only become active'
            USING ERRCODE = '23514';
    ELSIF OLD.status = 'ACTIVE' AND NEW.status <> 'ROLLED_BACK' THEN
        RAISE EXCEPTION 'active deployment can only be rolled back'
            USING ERRCODE = '23514';
    ELSIF OLD.status IN ('REJECTED', 'ROLLED_BACK')
            AND NEW.status <> OLD.status THEN
        RAISE EXCEPTION 'terminal deployment cannot leave its state'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.status = 'APPROVED'
            AND (NEW.quality_approved_by IS NULL
                OR NEW.release_approved_by IS NULL
                OR NEW.quality_approved_by = NEW.release_approved_by) THEN
        RAISE EXCEPTION 'approved deployment requires two distinct approvals'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'ACTIVE'
            AND (NEW.warmup_evidence_sha256 IS NULL
                OR NEW.metrics_gate_sha256 IS NULL) THEN
        RAISE EXCEPTION 'active deployment requires warmup and metrics evidence'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'ROLLED_BACK'
            AND (NEW.rollback_model_version_id IS NULL
                OR NEW.rollback_model_version_id = NEW.model_version_id
                OR NOT EXISTS (
                    SELECT 1 FROM model_version mv
                    WHERE mv.model_version_id = NEW.rollback_model_version_id
                      AND mv.approval_state = 'APPROVED'
                )) THEN
        RAISE EXCEPTION 'rollback target must be a distinct approved model version'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_model_deployment_supply_chain_guard
    BEFORE UPDATE ON model_deployment
    FOR EACH ROW EXECUTE FUNCTION td_guard_model_deployment();

CREATE OR REPLACE FUNCTION td_guard_model_deployment_approval()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    requester uuid;
    other_actor uuid;
BEGIN
    SELECT requested_by INTO requester
    FROM model_deployment
    WHERE model_deployment_id = NEW.model_deployment_id;
    IF requester IS NULL OR requester = NEW.actor_id THEN
        RAISE EXCEPTION 'deployment requester cannot approve its own deployment'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.decision = 'APPROVE' THEN
        SELECT actor_id INTO other_actor
        FROM model_deployment_approval
        WHERE model_deployment_id = NEW.model_deployment_id
          AND role <> NEW.role
          AND decision = 'APPROVE';
        IF other_actor = NEW.actor_id THEN
            RAISE EXCEPTION 'deployment approvals must have distinct actors'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_model_deployment_approval_guard
    BEFORE INSERT ON model_deployment_approval
    FOR EACH ROW EXECUTE FUNCTION td_guard_model_deployment_approval();

CREATE INDEX idx_model_deployment_rollback_target
    ON model_deployment(rollback_model_version_id)
    WHERE rollback_model_version_id IS NOT NULL;
