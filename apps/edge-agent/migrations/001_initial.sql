PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS capture_queue (
    capture_id TEXT PRIMARY KEY,
    station_id TEXT NOT NULL,
    recipe_id TEXT NOT NULL,
    client_sequence INTEGER NOT NULL,
    trigger_id TEXT NOT NULL,
    trigger_source TEXT NOT NULL CHECK (
        trigger_source IN ('PLC', 'SENSOR', 'MANUAL', 'HISTORICAL_IMPORT')
    ),
    occurred_at TEXT NOT NULL,
    quality_status TEXT NOT NULL CHECK (
        quality_status IN ('OK', 'WARNING', 'REJECTED')
    ),
    quality_warnings_json TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL CHECK (
        state IN (
            'PENDING', 'UPLOADING', 'UPLOADED', 'SUBMITTED',
            'WAIT_RESULT', 'DONE', 'RETRY_WAIT', 'LOCAL_DEAD'
        )
    ),
    manifest_path TEXT NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    retry_at REAL,
    resume_state TEXT,
    next_poll_at REAL,
    central_status TEXT,
    error_code TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    confirmed_at REAL
);

CREATE INDEX IF NOT EXISTS idx_capture_queue_due
    ON capture_queue(state, retry_at, created_at);

CREATE TABLE IF NOT EXISTS local_image (
    capture_id TEXT NOT NULL,
    image_role TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (
        length(sha256) = 64
        AND sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    size_bytes INTEGER NOT NULL CHECK (size_bytes > 0),
    width INTEGER NOT NULL CHECK (width > 0),
    height INTEGER NOT NULL CHECK (height > 0),
    media_type TEXT NOT NULL,
    upload_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        upload_status IN (
            'PENDING', 'UPLOADING', 'UPLOADED', 'AVAILABLE', 'FAILED'
        )
    ),
    central_image_id TEXT,
    upload_receipt TEXT,
    PRIMARY KEY (capture_id, image_role),
    FOREIGN KEY (capture_id) REFERENCES capture_queue(capture_id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS sync_attempt (
    request_id TEXT PRIMARY KEY,
    capture_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    result TEXT,
    error_code TEXT,
    FOREIGN KEY (capture_id) REFERENCES capture_queue(capture_id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_sync_attempt_capture
    ON sync_attempt(capture_id, started_at);

CREATE TABLE IF NOT EXISTS trigger_event (
    source TEXT NOT NULL,
    trigger_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    occurred_monotonic REAL NOT NULL,
    related_trigger_id TEXT,
    capture_id TEXT,
    outcome_status TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    error_code TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (source, trigger_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_trigger_event_capture
    ON trigger_event(capture_id)
    WHERE capture_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_trigger_event_source_sequence
    ON trigger_event(source, occurred_monotonic DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cleanup_audit (
    capture_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    central_status TEXT NOT NULL,
    sha256_json TEXT NOT NULL,
    requested_at REAL NOT NULL,
    completed_at REAL,
    FOREIGN KEY (capture_id) REFERENCES capture_queue(capture_id)
        ON DELETE RESTRICT
);

INSERT OR IGNORE INTO agent_state(key, value, updated_at)
VALUES ('schema_version', '1', CAST(strftime('%s', 'now') AS REAL));
