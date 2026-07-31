-- P6-03：训练工人只能通过受控状态回报推进运行，技术来源锁不可变。

ALTER TABLE training_run
    ADD COLUMN failure_code varchar(128),
    ADD CONSTRAINT ck_training_failure_code
        CHECK (failure_code IS NULL OR length(trim(failure_code)) BETWEEN 1 AND 128);

CREATE OR REPLACE FUNCTION td_guard_training_run()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF ROW(
        NEW.dataset_version_id,
        NEW.code_commit,
        NEW.config,
        NEW.config_sha256,
        NEW.environment_lock_sha256,
        NEW.random_seed
    ) IS DISTINCT FROM ROW(
        OLD.dataset_version_id,
        OLD.code_commit,
        OLD.config,
        OLD.config_sha256,
        OLD.environment_lock_sha256,
        OLD.random_seed
    ) THEN
        RAISE EXCEPTION 'training source locks are immutable'
            USING ERRCODE = '55000';
    END IF;

    IF NOT (
        NEW.status = OLD.status
        OR (OLD.status = 'QUEUED'
            AND NEW.status IN ('RUNNING', 'FAILED', 'CANCELLED'))
        OR (OLD.status = 'RUNNING'
            AND NEW.status IN ('SUCCEEDED', 'FAILED', 'CANCELLED'))
    ) THEN
        RAISE EXCEPTION 'illegal training status transition: % -> %',
            OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;

    IF NEW.status = 'RUNNING'
            AND (NEW.started_at IS NULL OR NEW.finished_at IS NOT NULL
                OR NEW.failure_code IS NOT NULL) THEN
        RAISE EXCEPTION 'running training requires only started_at'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'SUCCEEDED'
            AND (NEW.registry_run_uri IS NULL
                OR NEW.started_at IS NULL
                OR NEW.finished_at IS NULL
                OR NEW.finished_at < NEW.started_at
                OR NEW.failure_code IS NOT NULL) THEN
        RAISE EXCEPTION 'succeeded training requires completion evidence'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status IN ('FAILED', 'CANCELLED')
            AND (NEW.finished_at IS NULL OR NEW.failure_code IS NULL) THEN
        RAISE EXCEPTION 'failed or cancelled training requires failure evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_training_run_status_guard
    BEFORE UPDATE ON training_run
    FOR EACH ROW EXECUTE FUNCTION td_guard_training_run();
