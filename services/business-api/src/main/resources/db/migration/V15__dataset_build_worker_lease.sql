-- 数据集构建执行端使用有期限的领取事实，避免多个执行端同时处理同一版本。
-- 执行端异常退出后，BUILDING 任务可在租约过期后被安全重新领取。

ALTER TABLE dataset_version
    ADD COLUMN build_worker_id varchar(128),
    ADD COLUMN build_claimed_at timestamptz,
    ADD CONSTRAINT ck_dataset_build_claim_pair CHECK (
        (build_worker_id IS NULL AND build_claimed_at IS NULL)
        OR (
            status = 'BUILDING'
            AND build_worker_id IS NOT NULL
            AND build_claimed_at IS NOT NULL
        )
    );

CREATE INDEX idx_dataset_version_build_claim
    ON dataset_version(created_at, dataset_version_id)
    WHERE status = 'BUILDING';

COMMENT ON COLUMN dataset_version.build_worker_id IS
    '当前数据集构建执行端；仅在 BUILDING 状态使用';
COMMENT ON COLUMN dataset_version.build_claimed_at IS
    '构建任务租约起点；执行端异常退出后允许超时重领';
