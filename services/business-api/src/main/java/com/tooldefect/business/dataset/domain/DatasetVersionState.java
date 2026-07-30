package com.tooldefect.business.dataset.domain;

/** 数据集版本一旦冻结即不可原位修改。 */
public enum DatasetVersionState {
    BUILDING,
    VALIDATING,
    FROZEN,
    REJECTED
}
