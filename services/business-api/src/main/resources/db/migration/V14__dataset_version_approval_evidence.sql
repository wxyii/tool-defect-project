-- 数据集版本冻结必须保留独立审批时间；历史冻结行不猜测回填审批事实。

ALTER TABLE dataset_version
    ADD COLUMN approved_at timestamptz;

ALTER TABLE dataset_version
    ADD CONSTRAINT ck_dataset_version_approval_evidence
    CHECK (
        status <> 'FROZEN'
        OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)
    ) NOT VALID;
