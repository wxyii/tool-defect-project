-- 追加事实不可更新或删除；纠错必须新增记录并更新显式投影。

CREATE OR REPLACE FUNCTION td_reject_fact_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'table % is append-only; insert a superseding record', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_detection_result_append_only
    BEFORE UPDATE OR DELETE ON detection_result
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

CREATE TRIGGER trg_defect_region_append_only
    BEFORE UPDATE OR DELETE ON defect_region
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

CREATE TRIGGER trg_disposition_record_append_only
    BEFORE UPDATE OR DELETE ON disposition_record
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

CREATE TRIGGER trg_review_record_append_only
    BEFORE UPDATE OR DELETE ON review_record
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

CREATE TRIGGER trg_audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION td_reject_fact_mutation();

-- 发布器在同一短事务中使用以下语义领取，多个实例不会重复领取同一行：
-- SELECT event_id
-- FROM outbox_event
-- WHERE status IN ('NEW', 'FAILED') AND next_attempt_at <= now()
-- ORDER BY created_at
-- FOR UPDATE SKIP LOCKED
-- LIMIT :batch_size;

CREATE INDEX idx_inbox_processed_at
    ON inbox_message(processed_at)
    WHERE status = 'PROCESSED';
