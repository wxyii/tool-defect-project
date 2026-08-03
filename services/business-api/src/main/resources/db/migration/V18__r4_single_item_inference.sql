-- R4：产线单项映射、第二版推理终态引用和正确的全失败聚合。

CREATE TABLE production_capture_item_v2 (
    capture_id uuid PRIMARY KEY,
    batch_item_id uuid NOT NULL UNIQUE REFERENCES detection_batch_item_v2(batch_item_id),
    device_subject varchar(256) NOT NULL CHECK (length(trim(device_subject)) > 0),
    source_sha256 char(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE detection_item_result_v2 (
    detection_task_id uuid PRIMARY KEY REFERENCES detection_task_v2(detection_task_id),
    batch_item_id uuid NOT NULL UNIQUE REFERENCES detection_batch_item_v2(batch_item_id),
    message_id uuid NOT NULL UNIQUE,
    attempt_id uuid NOT NULL,
    terminal_kind varchar(24) NOT NULL CHECK (
        terminal_kind IN ('COMPLETED', 'QUALITY_REJECTED', 'FAILED')
    ),
    algorithm_outcome varchar(24) CHECK (
        algorithm_outcome IS NULL
        OR algorithm_outcome IN ('QUALIFIED', 'UNQUALIFIED', 'INCONCLUSIVE')
    ),
    result_bucket varchar(128),
    result_object_key varchar(1024),
    result_object_version varchar(256),
    result_sha256 char(64) CHECK (result_sha256 IS NULL OR result_sha256 ~ '^[0-9a-f]{64}$'),
    result_size_bytes bigint CHECK (result_size_bytes IS NULL OR result_size_bytes > 0),
    error_code varchar(100),
    retryable boolean,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_detection_item_result_v2_terminal CHECK (
        (terminal_kind = 'FAILED' AND algorithm_outcome IS NULL
          AND result_bucket IS NULL AND result_object_key IS NULL
          AND result_sha256 IS NULL AND result_size_bytes IS NULL
          AND error_code IS NOT NULL AND retryable IS NOT NULL)
        OR
        (terminal_kind IN ('COMPLETED', 'QUALITY_REJECTED')
          AND algorithm_outcome IS NOT NULL AND result_bucket IS NOT NULL
          AND result_object_key IS NOT NULL AND result_sha256 IS NOT NULL
          AND result_size_bytes IS NOT NULL AND error_code IS NULL
          AND retryable IS NULL)
    )
);

CREATE OR REPLACE FUNCTION td_recompute_detection_batch_v2(p_batch_id uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    summary record;
    current_batch record;
    next_status varchar(32);
BEGIN
    SELECT status, source, legacy_read_only INTO current_batch
    FROM detection_batch_v2 WHERE batch_id = p_batch_id FOR UPDATE;

    SELECT
        count(*)::integer AS total,
        count(*) FILTER (WHERE status IN ('COMPLETED', 'QUALITY_REJECTED', 'FAILED', 'CANCELLED'))::integer AS completed,
        count(*) FILTER (WHERE status = 'COMPLETED' AND algorithm_outcome = 'UNQUALIFIED')::integer AS defect_suspected,
        count(*) FILTER (WHERE status = 'COMPLETED' AND algorithm_outcome = 'QUALIFIED')::integer AS normal,
        count(*) FILTER (WHERE status = 'COMPLETED' AND algorithm_outcome = 'INCONCLUSIVE')::integer AS inconclusive,
        count(*) FILTER (WHERE status = 'QUALITY_REJECTED')::integer AS quality_rejected,
        count(*) FILTER (WHERE status = 'FAILED')::integer AS technical_failed,
        count(*) FILTER (WHERE status IN ('PENDING_UPLOAD', 'UPLOADING'))::integer AS uploading,
        count(*) FILTER (WHERE status = 'READY')::integer AS ready,
        count(*) FILTER (WHERE status IN ('QUEUED', 'PROCESSING'))::integer AS active
    INTO summary FROM detection_batch_item_v2 WHERE batch_id = p_batch_id;

    next_status := CASE
        WHEN current_batch.source = 'MANUAL_UPLOAD'
             AND current_batch.status IN ('DRAFT', 'UPLOADING', 'READY')
             AND summary.active = 0
            THEN CASE
                WHEN summary.total = 0 THEN 'DRAFT'
                WHEN summary.uploading > 0 THEN 'UPLOADING'
                WHEN summary.ready = summary.total THEN 'READY'
                ELSE 'UPLOADING'
            END
        WHEN summary.total = 0 THEN 'FAILED'
        WHEN summary.completed < summary.total THEN 'PROCESSING'
        WHEN summary.technical_failed + summary.quality_rejected = summary.total THEN 'FAILED'
        WHEN summary.technical_failed > 0 OR summary.quality_rejected > 0 THEN 'PARTIALLY_COMPLETED'
        ELSE 'COMPLETED'
    END;

    UPDATE detection_batch_v2 SET
        total_count = summary.total,
        completed_count = summary.completed,
        defect_suspected_count = summary.defect_suspected,
        normal_count = summary.normal,
        inconclusive_count = summary.inconclusive,
        quality_rejected_count = summary.quality_rejected,
        technical_failed_count = summary.technical_failed,
        status = next_status,
        updated_at = now(),
        record_version = record_version + 1
    WHERE batch_id = p_batch_id;
END;
$$;
