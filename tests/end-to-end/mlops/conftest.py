"""模型生命周期端到端测试共享数据与环境。

本项目使用 unittest discover 运行测试，因此本模块提供可导入的
常量、工厂与辅助函数，而不是 pytest 风格的 fixture 定义。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Optional


def new_uuid() -> str:
    return str(uuid.uuid4())


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 测试用固定标识符（确定性全链路追踪）
# ---------------------------------------------------------------------------

DATASET_ID = "ds-019f0000-0000-7000-8000-000000000001"
DATASET_VERSION_ID = "dsv-019f0000-0000-7000-8000-000000000002"
CANDIDATE_MANIFEST_ID = "cm-019f0000-0000-7000-8000-000000000003"
TRAINING_RUN_ID = "tr-019f0000-0000-7000-8000-000000000004"
MODEL_VERSION_ID = "mv-019f0000-0000-7000-8000-000000000005"
MODEL_VERSION_ID_V2 = "mv-019f0000-0000-7000-8000-000000000006"
DEPLOYMENT_ID_SHADOW = "dep-019f0000-0000-7000-8000-000000000007"
DEPLOYMENT_ID_CANARY = "dep-019f0000-0000-7000-8000-000000000008"
DEPLOYMENT_ID_PRODUCTION = "dep-019f0000-0000-7000-8000-000000000009"

STATION_IDS = [
    "station-019f0000-0000-7000-8000-000000000010",
    "station-019f0000-0000-7000-8000-000000000011",
]

EVALUATION_REPORT_SHA256 = sha256("evaluation-report-content")

# 模拟训练非确定性输出
TRAINING_OUTPUT_HASH = sha256("model-weights-binary-v1")
TRAINING_OUTPUT_HASH_V2 = sha256("model-weights-binary-v2")


@dataclass
class DeploymentRecord:
    deployment_id: str
    model_version_id: str
    environment: str
    strategy: str
    station_ids: list[str]
    traffic_ratio: float
    rollback_model_version_id: str
    status: str = "PENDING_APPROVAL"
    approvals: list[dict[str, str]] = field(default_factory=list)
    version: int = 0


@dataclass
class RollbackRecord:
    rollback_id: str
    deployment_id: str
    from_model_version_id: str
    target_model_version_id: str
    reason: str
    status: str = "QUEUED"
    created_at: str = "2026-07-30T00:00:00Z"


def build_evaluation_report(
    model_version_id: str = MODEL_VERSION_ID,
) -> dict:
    return {
        "model_version_id": model_version_id,
        "sha256": EVALUATION_REPORT_SHA256,
        "metrics": {
            "precision": 0.95,
            "recall": 0.94,
            "f1_score": 0.945,
            "mAP": 0.92,
        },
        "dataset_version_id": DATASET_VERSION_ID,
        "evaluated_at": "2026-07-30T01:00:00Z",
    }
