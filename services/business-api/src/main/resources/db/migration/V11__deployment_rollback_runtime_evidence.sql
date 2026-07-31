ALTER TABLE model_deployment
    ADD COLUMN rollback_evidence_sha256 char(64),
    ADD CONSTRAINT ck_model_deployment_rollback_hash
        CHECK (rollback_evidence_sha256 IS NULL OR rollback_evidence_sha256 ~ '^[0-9a-f]{64}$');

CREATE OR REPLACE FUNCTION td_guard_model_deployment_rollback_evidence()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status = 'ROLLED_BACK'
            AND (NEW.rollback_evidence_sha256 IS NULL
                OR NEW.rollback_evidence_sha256 !~ '^[0-9a-f]{64}$') THEN
        RAISE EXCEPTION 'rolled back deployment requires runtime evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_model_deployment_rollback_evidence_guard
    BEFORE UPDATE ON model_deployment
    FOR EACH ROW EXECUTE FUNCTION td_guard_model_deployment_rollback_evidence();
