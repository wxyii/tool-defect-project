"""P6-08 模型生命周期端到端测试。

覆盖候选样本审批 → 数据集版本 → 训练运行 → 模型注册与验证 →
Shadow → Canary → Production 部署 → 回滚 → 全链路追踪。
"""

from __future__ import annotations

import hashlib
import unittest
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Optional


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
EVALUATION_REPORT_SHA256 = hashlib.sha256(b"evaluation-report-content").hexdigest()
TRAINING_OUTPUT_HASH = hashlib.sha256(b"model-weights-binary-v1").hexdigest()
TRAINING_OUTPUT_HASH_V2 = hashlib.sha256(b"model-weights-binary-v2").hexdigest()


def _new_uuid() -> str:
    return str(_uuid.uuid4())


@dataclass
class _DeploymentRecord:
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
class _RollbackRecord:
    rollback_id: str
    deployment_id: str
    from_model_version_id: str
    target_model_version_id: str
    reason: str
    status: str = "QUEUED"
    created_at: str = "2026-07-30T00:00:00Z"


# ---------------------------------------------------------------------------
# 领域异常
# ---------------------------------------------------------------------------


class LifecycleConflict(RuntimeError):
    """状态冲突：当前生命周期阶段不允许该操作。"""


class Forbidden(RuntimeError):
    """权限不足：缺少角色或职责分离要求不满足。"""


# ---------------------------------------------------------------------------
# 模型生命周期状态机（与 OpenAPI v1 契约对齐）
# ---------------------------------------------------------------------------


@dataclass
class MlopsLifecycle:
    """模拟中心侧 MLOps 领域状态机，离线端到端可验证。

    所有状态转换与 contracts/openapi/tool-defect-api-v1.json 的
    mlops 标签下路径一一对应。
    """

    # 候选样本
    candidate_approved_samples: dict[str, set[str]] = field(default_factory=dict)

    # 数据集版本
    dataset_versions: dict[str, dict] = field(default_factory=dict)

    # 训练运行
    training_runs: dict[str, dict] = field(default_factory=dict)

    # 模型注册
    model_registry: dict[str, dict] = field(default_factory=dict)

    # 验证决策
    validation_decisions: dict[str, list[dict]] = field(default_factory=dict)

    # 部署
    deployments: dict[str, _DeploymentRecord] = field(default_factory=dict)

    # 回滚
    rollbacks: dict[str, list[_RollbackRecord]] = field(default_factory=dict)

    # 审计分类账
    audit_ledger: list[dict] = field(default_factory=list)

    # 活跃生产模型版本
    active_production_model: Optional[str] = None

    # 上一个生产模型版本（回滚链）
    previous_production_model: Optional[str] = None

    # ------------------------------------------------------------------
    # 1. 候选样本审批
    # ------------------------------------------------------------------

    def approve_candidate_samples(
        self,
        manifest_id: str,
        sample_ids: list[str],
        approved_by: str,
    ) -> None:
        if not sample_ids:
            raise LifecycleConflict("样本列表不能为空")
        if manifest_id in self.candidate_approved_samples:
            raise LifecycleConflict("同一清单不可重复审批")
        existing = self.candidate_approved_samples.setdefault(manifest_id, set())
        for sample_id in sample_ids:
            if sample_id in existing:
                raise LifecycleConflict(f"样本 {sample_id} 已被审批")
        existing.update(sample_ids)
        self._audit("CANDIDATE_APPROVED", manifest_id, approved_by, {"sample_count": len(sample_ids)})

    # ------------------------------------------------------------------
    # 2. 数据集版本创建与审批
    # ------------------------------------------------------------------

    def create_dataset_version(
        self,
        dataset_version_id: str,
        dataset_id: str,
        candidate_manifest_id: str,
        purpose: str,
        created_by: str,
    ) -> dict:
        if dataset_version_id in self.dataset_versions:
            raise LifecycleConflict("数据集版本已存在")

        if candidate_manifest_id not in self.candidate_approved_samples:
            raise LifecycleConflict(
                f"候选清单 {candidate_manifest_id} 尚未通过审批，不可用于构建数据集"
            )

        sample_ids = self.candidate_approved_samples[candidate_manifest_id]
        if not sample_ids:
            raise LifecycleConflict("候选清单中没有已审批样本")

        record = {
            "dataset_version_id": dataset_version_id,
            "dataset_id": dataset_id,
            "candidate_manifest_id": candidate_manifest_id,
            "purpose": purpose,
            "sample_count": len(sample_ids),
            "status": "DRAFT",
            "version": 1,
            "created_by": created_by,
            "created_at": "2026-07-30T00:01:00Z",
            "sample_ids": list(sample_ids),
        }
        self.dataset_versions[dataset_version_id] = record
        self._audit("DATASET_VERSION_CREATED", dataset_version_id, created_by, {"purpose": purpose})
        return dict(record)

    def approve_dataset_version(
        self,
        dataset_version_id: str,
        approved_by: str,
    ) -> dict:
        record = self._require_entity(self.dataset_versions, dataset_version_id, "数据集版本")
        if record["status"] == "APPROVED":
            raise LifecycleConflict("数据集版本已审批")
        if record["status"] != "DRAFT":
            raise LifecycleConflict(f"数据集版本状态为 {record['status']}，不可审批")
        if record.get("created_by") == approved_by:
            raise Forbidden("数据集创建人与审批人不得为同一人")

        record["status"] = "APPROVED"
        record["approved_by"] = approved_by
        record["version"] += 1
        self._audit("DATASET_VERSION_APPROVED", dataset_version_id, approved_by, {})
        return dict(record)

    def get_dataset_version(self, dataset_version_id: str) -> dict:
        return self._require_entity(self.dataset_versions, dataset_version_id, "数据集版本")

    # ------------------------------------------------------------------
    # 3. 训练运行创建与监控
    # ------------------------------------------------------------------

    def create_training_run(
        self,
        dataset_version_id: str,
        training_config_version: str,
        initial_model_version_id: Optional[str],
        created_by: str,
    ) -> dict:
        dataset = self._require_entity(self.dataset_versions, dataset_version_id, "数据集版本")
        if dataset["status"] != "APPROVED":
            raise LifecycleConflict(
                f"数据集版本状态为 {dataset['status']}，必须为 APPROVED 才可发起训练"
            )

        run_id = _new_uuid()

        record = {
            "training_run_id": run_id,
            "dataset_version_id": dataset_version_id,
            "training_config_version": training_config_version,
            "initial_model_version_id": initial_model_version_id,
            "status": "QUEUED",
            "created_by": created_by,
            "created_at": "2026-07-30T00:02:00Z",
            "metrics": None,
            "output_hash": None,
        }
        self.training_runs[run_id] = record
        self._audit("TRAINING_RUN_CREATED", run_id, created_by, {
            "dataset_version_id": dataset_version_id,
            "training_config_version": training_config_version,
        })
        return dict(record)

    def mark_training_running(self, training_run_id: str) -> dict:
        record = self._require_entity(self.training_runs, training_run_id, "训练运行")
        if record["status"] not in {"QUEUED", "RETRY_WAIT"}:
            raise LifecycleConflict(f"训练运行状态为 {record['status']}，不可启动")
        record["status"] = "RUNNING"
        self._audit("TRAINING_RUN_STARTED", training_run_id, "system", {})
        return dict(record)

    def complete_training_run(
        self,
        training_run_id: str,
        output_hash: str,
        metrics: dict,
    ) -> dict:
        record = self._require_entity(self.training_runs, training_run_id, "训练运行")
        if record["status"] != "RUNNING":
            raise LifecycleConflict(f"训练运行状态为 {record['status']}，不可完成")
        record["status"] = "SUCCEEDED"
        record["output_hash"] = output_hash
        record["metrics"] = metrics
        record["completed_at"] = "2026-07-30T01:00:00Z"
        self._audit("TRAINING_RUN_COMPLETED", training_run_id, "system", {"output_hash": output_hash})
        return dict(record)

    def fail_training_run(self, training_run_id: str, error: str) -> dict:
        record = self._require_entity(self.training_runs, training_run_id, "训练运行")
        if record["status"] not in {"QUEUED", "RUNNING", "RETRY_WAIT"}:
            raise LifecycleConflict(f"训练运行状态为 {record['status']}，不可标记失败")
        record["status"] = "FAILED"
        record["error"] = error
        self._audit("TRAINING_RUN_FAILED", training_run_id, "system", {"error": error})
        return dict(record)

    def get_training_run(self, training_run_id: str) -> dict:
        return self._require_entity(self.training_runs, training_run_id, "训练运行")

    # ------------------------------------------------------------------
    # 4. 模型注册与验证
    # ------------------------------------------------------------------

    def register_model(
        self,
        model_version_id: str,
        training_run_id: str,
        registered_by: str,
    ) -> dict:
        if model_version_id in self.model_registry:
            raise LifecycleConflict("该模型版本已注册")

        training = self._require_entity(self.training_runs, training_run_id, "训练运行")
        if training["status"] != "SUCCEEDED":
            raise LifecycleConflict(
                f"训练运行状态为 {training['status']}，必须为 SUCCEEDED 才可注册模型"
            )

        record = {
            "model_version_id": model_version_id,
            "training_run_id": training_run_id,
            "output_hash": training["output_hash"],
            "status": "DRAFT",
            "registered_by": registered_by,
            "registered_at": "2026-07-30T01:01:00Z",
            "dataset_version_id": training["dataset_version_id"],
        }
        self.model_registry[model_version_id] = record
        self._audit("MODEL_REGISTERED", model_version_id, registered_by, {
            "training_run_id": training_run_id,
        })
        return dict(record)

    def submit_validation_decision(
        self,
        model_version_id: str,
        decision: str,
        reason: str,
        evaluation_report_sha256: str,
        decided_by: str,
    ) -> dict:
        model = self._require_entity(self.model_registry, model_version_id, "模型版本")
        if decision not in {"APPROVE", "REJECT"}:
            raise LifecycleConflict(f"无效验证决策: {decision}")

        valid_from = {"DRAFT": "DRAFT", "VALIDATING": "VALIDATING"}
        if model["status"] not in valid_from:
            raise LifecycleConflict(
                f"模型版本状态为 {model['status']}，不可提交验证决策"
            )

        decision_record = {
            "decision": decision,
            "reason": reason,
            "evaluation_report_sha256": evaluation_report_sha256,
            "decided_by": decided_by,
            "decided_at": "2026-07-30T02:00:00Z",
        }
        self.validation_decisions.setdefault(model_version_id, []).append(decision_record)

        if model.get("registered_by") == decided_by:
            raise Forbidden("模型注册人不得担任验证人")

        model["status"] = "VALIDATING"
        if decision == "APPROVE":
            model["status"] = "APPROVED"
            model["approved_by"] = decided_by
        else:
            model["status"] = "REJECTED"
            model["rejected_by"] = decided_by

        self._audit("VALIDATION_DECIDED", model_version_id, decided_by, {
            "decision": decision,
            "sha256": evaluation_report_sha256,
        })
        return dict(model)

    def get_model_version(self, model_version_id: str) -> dict:
        return self._require_entity(self.model_registry, model_version_id, "模型版本")

    # ------------------------------------------------------------------
    # 5. 模型部署 (shadow / canary / production)
    # ------------------------------------------------------------------

    def create_deployment(
        self,
        deployment_id: str,
        model_version_id: str,
        environment: str,
        strategy: str,
        station_ids: list[str],
        traffic_ratio: float,
        rollback_model_version_id: str,
        created_by: str,
    ) -> _DeploymentRecord:
        if environment not in {"SHADOW", "CANARY", "PRODUCTION"}:
            raise LifecycleConflict(f"无效部署环境: {environment}")

        model = self._require_entity(self.model_registry, model_version_id, "模型版本")

        deployable_statuses = {"APPROVED", "SHADOW", "CANARY"}
        if model["status"] not in deployable_statuses:
            raise LifecycleConflict(
                f"模型版本状态为 {model['status']}，必须为已审批或已部分部署才可部署"
            )

        env_order = {"APPROVED": 0, "SHADOW": 1, "CANARY": 2, "PRODUCTION": 3}
        current_env = model.get("status", "APPROVED")
        if env_order.get(environment, -1) <= env_order.get(current_env, -1):
            raise LifecycleConflict(
                f"模型当前已部署至 {current_env}，不可降级部署到 {environment}"
            )

        if environment == "PRODUCTION":
            if model_version_id == self.active_production_model:
                raise LifecycleConflict("该模型版本已是当前生产版本")

        deployment = _DeploymentRecord(
            deployment_id=deployment_id,
            model_version_id=model_version_id,
            environment=environment,
            strategy=strategy,
            station_ids=list(station_ids),
            traffic_ratio=traffic_ratio,
            rollback_model_version_id=rollback_model_version_id,
        )
        self.deployments[deployment_id] = deployment
        self._audit("DEPLOYMENT_CREATED", deployment_id, created_by, {
            "model_version_id": model_version_id,
            "environment": environment,
        })
        return deployment

    def approve_deployment(
        self,
        deployment_id: str,
        role: str,
        decision: str,
        reason: str,
        approved_by: str,
    ) -> _DeploymentRecord:
        deployment = self._require_entity(self.deployments, deployment_id, "部署")
        if role not in {"QUALITY_APPROVER", "MODEL_RELEASE_APPROVER"}:
            raise LifecycleConflict(f"无效审批角色: {role}")

        existing_roles = {a["role"] for a in deployment.approvals}
        if role in existing_roles:
            raise LifecycleConflict(f"角色 {role} 已提交审批")

        deployment.approvals.append({
            "role": role,
            "decision": decision,
            "reason": reason,
            "approved_by": str(approved_by),
        })

        if len(deployment.approvals) >= 2:
            if all(a["decision"] == "APPROVE" for a in deployment.approvals):
                deployment.status = "DEPLOYING"
            else:
                deployment.status = "REJECTED"

        deployment.version += 1
        self._audit("DEPLOYMENT_APPROVED", deployment_id, approved_by, {
            "role": role,
            "decision": decision,
        })
        return deployment

    def activate_deployment(self, deployment_id: str) -> _DeploymentRecord:
        deployment = self._require_entity(self.deployments, deployment_id, "部署")
        if deployment.status != "DEPLOYING":
            raise LifecycleConflict(
                f"部署状态为 {deployment.status}，必须为 DEPLOYING 才可激活"
            )

        model = self.model_registry[deployment.model_version_id]
        env = deployment.environment

        if env == "PRODUCTION":
            self.previous_production_model = self.active_production_model
            self.active_production_model = deployment.model_version_id

        model["status"] = env
        deployment.status = env
        self._audit("DEPLOYMENT_ACTIVATED", deployment_id, "system", {
            "environment": env,
            "model_version_id": deployment.model_version_id,
        })
        return deployment

    def get_deployment(self, deployment_id: str) -> _DeploymentRecord:
        return self._require_entity(self.deployments, deployment_id, "部署")

    # ------------------------------------------------------------------
    # 6. 模型回滚
    # ------------------------------------------------------------------

    def rollback_deployment(
        self,
        deployment_id: str,
        target_model_version_id: str,
        reason: str,
        initiated_by: str,
    ) -> _RollbackRecord:
        deployment = self._require_entity(self.deployments, deployment_id, "部署")
        if deployment.environment != "PRODUCTION":
            raise LifecycleConflict("仅生产环境部署支持回滚")
        if deployment.status != "PRODUCTION":
            raise LifecycleConflict(f"部署状态为 {deployment.status}，不可回滚")

        target_model = self._require_entity(
            self.model_registry, target_model_version_id, "目标模型版本"
        )
        if target_model["status"] not in {"PRODUCTION", "RETIRED"}:
            raise LifecycleConflict(
                f"目标模型版本状态为 {target_model['status']}，不可作为回滚目标"
            )

        if target_model_version_id == deployment.model_version_id:
            raise LifecycleConflict("回滚目标不可与当前版本相同")

        rollback = _RollbackRecord(
            rollback_id=_new_uuid(),
            deployment_id=deployment_id,
            from_model_version_id=deployment.model_version_id,
            target_model_version_id=target_model_version_id,
            reason=reason,
            status="QUEUED",
        )
        self.rollbacks.setdefault(deployment_id, []).append(rollback)

        self._audit("ROLLBACK_QUEUED", deployment_id, initiated_by, {
            "target_model_version_id": target_model_version_id,
            "reason": reason,
        })
        return rollback

    def complete_rollback(self, deployment_id: str, rollback_id: str) -> _RollbackRecord:
        records = self.rollbacks.get(deployment_id, [])
        target = next((r for r in records if r.rollback_id == rollback_id), None)
        if target is None:
            raise LifecycleConflict(f"回滚记录 {rollback_id} 不存在")
        if target.status != "QUEUED":
            raise LifecycleConflict(f"回滚状态为 {target.status}，不可完成")

        target.status = "COMPLETED"

        deployment = self.deployments[deployment_id]
        deployment.status = "PRODUCTION"
        previous = self.active_production_model
        self.active_production_model = target.target_model_version_id
        self.previous_production_model = previous

        self._audit("ROLLBACK_COMPLETED", deployment_id, "system", {
            "rollback_id": rollback_id,
        })
        return target

    def get_rollback_history(self, deployment_id: str) -> list[_RollbackRecord]:
        return list(self.rollbacks.get(deployment_id, []))

    def get_audit_trail(self, entity_id: Optional[str] = None) -> list[dict]:
        if entity_id is None:
            return list(self.audit_ledger)
        return [e for e in self.audit_ledger if e["entity_id"] == entity_id]

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _require_entity(self, collection: dict, entity_id: str, label: str) -> dict:
        entity = collection.get(entity_id)
        if entity is None:
            raise LifecycleConflict(f"{label} {entity_id} 不存在")
        return entity

    def _audit(self, event: str, entity_id: str, actor: str, details: dict) -> None:
        self.audit_ledger.append({
            "event": event,
            "entity_id": entity_id,
            "actor": actor,
            "timestamp": "2026-07-30T00:00:00Z",
            "details": details,
            "sequence": len(self.audit_ledger) + 1,
        })


# =====================================================================
# 测试用例
# =====================================================================


class ModelLifecycleEndToEndTests(unittest.TestCase):

    def setUp(self):
        self.lifecycle = MlopsLifecycle()

        # 准备前置条件：审批候选样本
        self.lifecycle.approve_candidate_samples(
            CANDIDATE_MANIFEST_ID,
            ["sample-001", "sample-002", "sample-003"],
            "reviewer-a",
        )

    # ------------------------------------------------------------------
    # 数据集版本
    # ------------------------------------------------------------------

    def test_create_and_approve_dataset_version(self):
        ds = self.lifecycle.create_dataset_version(
            DATASET_VERSION_ID,
            DATASET_ID,
            CANDIDATE_MANIFEST_ID,
            "retraining-v2.0",
            "ml-engineer-1",
        )
        self.assertEqual(DATASET_VERSION_ID, ds["dataset_version_id"])
        self.assertEqual("DRAFT", ds["status"])
        self.assertEqual(3, ds["sample_count"])

        approved = self.lifecycle.approve_dataset_version(
            DATASET_VERSION_ID,
            "quality-lead",
        )
        self.assertEqual("APPROVED", approved["status"])
        self.assertEqual("quality-lead", approved["approved_by"])

    def test_cannot_self_approve(self):
        self.lifecycle.create_dataset_version(
            DATASET_VERSION_ID,
            DATASET_ID,
            CANDIDATE_MANIFEST_ID,
            "retraining-v2.0",
            "ml-engineer-1",
        )
        with self.assertRaises(Forbidden):
            self.lifecycle.approve_dataset_version(DATASET_VERSION_ID, "ml-engineer-1")

    def test_dataset_version_requires_approved_candidates(self):
        empty_lifecycle = MlopsLifecycle()
        with self.assertRaises(LifecycleConflict):
            empty_lifecycle.create_dataset_version(
                DATASET_VERSION_ID,
                DATASET_ID,
                CANDIDATE_MANIFEST_ID,
                "test",
                "ml-engineer-1",
            )

    # ------------------------------------------------------------------
    # 训练运行
    # ------------------------------------------------------------------

    def test_create_training_run(self):
        self._prepare_approved_dataset()
        run = self.lifecycle.create_training_run(
            DATASET_VERSION_ID,
            "config-v3.1",
            None,
            "ml-engineer-1",
        )
        run_id = run["training_run_id"]
        self.assertIsNotNone(run_id)
        self.assertEqual("QUEUED", run["status"])

        running = self.lifecycle.mark_training_running(run_id)
        self.assertEqual("RUNNING", running["status"])

        completed = self.lifecycle.complete_training_run(
            run_id,
            TRAINING_OUTPUT_HASH,
            {"mAP": 0.91, "loss": 0.12},
        )
        self.assertEqual("SUCCEEDED", completed["status"])
        self.assertEqual(TRAINING_OUTPUT_HASH, completed["output_hash"])

    def test_training_run_requires_approved_dataset(self):
        self.lifecycle.create_dataset_version(
            DATASET_VERSION_ID,
            DATASET_ID,
            CANDIDATE_MANIFEST_ID,
            "test",
            "ml-engineer-1",
        )
        with self.assertRaises(LifecycleConflict):
            self.lifecycle.create_training_run(
                DATASET_VERSION_ID,
                "config-v1",
                None,
                "ml-engineer-1",
            )

    def test_training_run_failure_is_recorded(self):
        self._prepare_approved_dataset()
        run = self.lifecycle.create_training_run(
            DATASET_VERSION_ID,
            "config-v3.1",
            None,
            "ml-engineer-1",
        )
        run_id = run["training_run_id"]
        self.lifecycle.mark_training_running(run_id)
        failed = self.lifecycle.fail_training_run(
            run_id,
            "GPU OOM at epoch 5",
        )
        self.assertEqual("FAILED", failed["status"])
        self.assertEqual("GPU OOM at epoch 5", failed["error"])

        # 失败后不可注册
        with self.assertRaises(LifecycleConflict):
            self.lifecycle.register_model(
                MODEL_VERSION_ID,
                run_id,
                "ml-engineer-1",
            )

    # ------------------------------------------------------------------
    # 模型注册与验证
    # ------------------------------------------------------------------

    def test_register_and_validate_model(self):
        self._prepare_completed_training()

        model = self.lifecycle.register_model(
            MODEL_VERSION_ID,
            self._run_id,
            "ml-engineer-1",
        )
        self.assertEqual("DRAFT", model["status"])
        self.assertEqual(self._run_id, model["training_run_id"])

        result = self.lifecycle.submit_validation_decision(
            MODEL_VERSION_ID,
            "APPROVE",
            "精度满足 P1 门禁要求",
            EVALUATION_REPORT_SHA256,
            "quality-lead",
        )
        self.assertEqual("APPROVED", result["status"])

    def test_validation_requires_different_person(self):
        self._prepare_completed_training()
        self.lifecycle.register_model(
            MODEL_VERSION_ID,
            self._run_id,
            "ml-engineer-1",
        )
        with self.assertRaises(Forbidden):
            self.lifecycle.submit_validation_decision(
                MODEL_VERSION_ID,
                "APPROVE",
                "自评通过",
                EVALUATION_REPORT_SHA256,
                "ml-engineer-1",
            )

    def test_model_can_be_rejected(self):
        self._prepare_completed_training()
        self.lifecycle.register_model(
            MODEL_VERSION_ID,
            self._run_id,
            "ml-engineer-1",
        )
        result = self.lifecycle.submit_validation_decision(
            MODEL_VERSION_ID,
            "REJECT",
            "召回率从 0.94 下降至 0.87",
            EVALUATION_REPORT_SHA256,
            "quality-lead",
        )
        self.assertEqual("REJECTED", result["status"])

        # 拒绝后不可部署
        with self.assertRaises(LifecycleConflict):
            self.lifecycle.create_deployment(
                DEPLOYMENT_ID_SHADOW,
                MODEL_VERSION_ID,
                "SHADOW",
                "STATION",
                [STATION_IDS[0]],
                0.0,
                MODEL_VERSION_ID,
                "deployer-1",
            )

    # ------------------------------------------------------------------
    # 部署
    # ------------------------------------------------------------------

    def _prepare_approved_model(self, model_version_id=MODEL_VERSION_ID):
        self._prepare_completed_training()
        self.lifecycle.register_model(model_version_id, self._run_id, "ml-engineer-1")
        self.lifecycle.submit_validation_decision(
            model_version_id,
            "APPROVE",
            "PASS",
            EVALUATION_REPORT_SHA256,
            "quality-lead",
        )

    def test_deploy_to_shadow(self):
        self._prepare_approved_model()
        dep = self._create_and_activate_deployment(DEPLOYMENT_ID_SHADOW, "SHADOW")
        self.assertEqual("SHADOW", dep.status)
        self.assertEqual("SHADOW", self.lifecycle.get_model_version(MODEL_VERSION_ID)["status"])

    def test_deploy_to_canary(self):
        self._prepare_approved_model()
        dep = self._create_and_activate_deployment(DEPLOYMENT_ID_CANARY, "CANARY")
        self.assertEqual("CANARY", dep.status)
        self.assertEqual("CANARY", self.lifecycle.get_model_version(MODEL_VERSION_ID)["status"])

    def test_deploy_to_production(self):
        self._prepare_approved_model()
        dep = self._create_and_activate_deployment(DEPLOYMENT_ID_PRODUCTION, "PRODUCTION")
        self.assertEqual("PRODUCTION", dep.status)
        self.assertEqual(MODEL_VERSION_ID, self.lifecycle.active_production_model)

    def test_deploy_requires_approvals(self):
        self._prepare_approved_model()
        self.lifecycle.create_deployment(
            DEPLOYMENT_ID_PRODUCTION,
            MODEL_VERSION_ID,
            "PRODUCTION",
            "STATION",
            STATION_IDS,
            1.0,
            MODEL_VERSION_ID,
            "deployer-1",
        )

        # 缺少审批时不可激活
        with self.assertRaises(LifecycleConflict):
            self.lifecycle.activate_deployment(DEPLOYMENT_ID_PRODUCTION)

        self.lifecycle.approve_deployment(
            DEPLOYMENT_ID_PRODUCTION,
            "QUALITY_APPROVER",
            "APPROVE",
            "质量验证通过",
            "quality-lead",
        )
        self.lifecycle.approve_deployment(
            DEPLOYMENT_ID_PRODUCTION,
            "MODEL_RELEASE_APPROVER",
            "APPROVE",
            "发布审批通过",
            "release-manager",
        )

        self.lifecycle.activate_deployment(DEPLOYMENT_ID_PRODUCTION)
        self.assertEqual(
            "PRODUCTION",
            self.lifecycle.get_deployment(DEPLOYMENT_ID_PRODUCTION).status,
        )

    # ------------------------------------------------------------------
    # 回滚
    # ------------------------------------------------------------------

    def test_rollback_model(self):
        self._prepare_approved_model()
        self._create_and_activate_deployment(DEPLOYMENT_ID_PRODUCTION, "PRODUCTION")

        # 注册第二个模型版本并部署
        self._prepare_approved_model_v2()
        self.lifecycle.create_deployment(
            "dep-v2-production",
            MODEL_VERSION_ID_V2,
            "PRODUCTION",
            "STATION",
            STATION_IDS,
            1.0,
            MODEL_VERSION_ID,
            "deployer-1",
        )
        self.lifecycle.approve_deployment("dep-v2-production", "QUALITY_APPROVER", "APPROVE", "ok", "quality-lead")
        self.lifecycle.approve_deployment("dep-v2-production", "MODEL_RELEASE_APPROVER", "APPROVE", "ok", "release-manager")
        self.lifecycle.activate_deployment("dep-v2-production")

        self.assertEqual(MODEL_VERSION_ID_V2, self.lifecycle.active_production_model)

        # 回滚到 v1
        rollback = self.lifecycle.rollback_deployment(
            "dep-v2-production",
            MODEL_VERSION_ID,
            "v2 生产指标劣化",
            "on-call-engineer",
        )
        self.assertEqual("QUEUED", rollback.status)

        completed = self.lifecycle.complete_rollback("dep-v2-production", rollback.rollback_id)
        self.assertEqual("COMPLETED", completed.status)
        self.assertEqual(MODEL_VERSION_ID, self.lifecycle.active_production_model)

    def test_rollback_preserves_history(self):
        self._prepare_approved_model()
        self._create_and_activate_deployment(DEPLOYMENT_ID_PRODUCTION, "PRODUCTION")

        self._prepare_approved_model_v2()
        self.lifecycle.create_deployment(
            "dep-v2-production",
            MODEL_VERSION_ID_V2,
            "PRODUCTION",
            "STATION",
            STATION_IDS,
            1.0,
            MODEL_VERSION_ID,
            "deployer-1",
        )
        self.lifecycle.approve_deployment("dep-v2-production", "QUALITY_APPROVER", "APPROVE", "ok", "quality-lead")
        self.lifecycle.approve_deployment("dep-v2-production", "MODEL_RELEASE_APPROVER", "APPROVE", "ok", "release-manager")
        self.lifecycle.activate_deployment("dep-v2-production")

        rollback = self.lifecycle.rollback_deployment(
            "dep-v2-production",
            MODEL_VERSION_ID,
            "v2 生产指标劣化",
            "on-call-engineer",
        )
        self.lifecycle.complete_rollback("dep-v2-production", rollback.rollback_id)

        history = self.lifecycle.get_rollback_history("dep-v2-production")
        self.assertEqual(1, len(history))
        self.assertEqual("COMPLETED", history[0].status)
        self.assertEqual(MODEL_VERSION_ID, history[0].target_model_version_id)
        self.assertEqual(MODEL_VERSION_ID_V2, history[0].from_model_version_id)

    def test_cannot_rollback_non_production(self):
        self._prepare_approved_model()
        self._create_and_activate_deployment(DEPLOYMENT_ID_SHADOW, "SHADOW")

        with self.assertRaises(LifecycleConflict):
            self.lifecycle.rollback_deployment(
                DEPLOYMENT_ID_SHADOW,
                MODEL_VERSION_ID,
                "test",
                "on-call-engineer",
            )

    def test_cannot_rollback_to_same_version(self):
        self._prepare_approved_model()
        self._create_and_activate_deployment(DEPLOYMENT_ID_PRODUCTION, "PRODUCTION")

        with self.assertRaises(LifecycleConflict):
            self.lifecycle.rollback_deployment(
                DEPLOYMENT_ID_PRODUCTION,
                MODEL_VERSION_ID,
                "同版本回滚无意义",
                "on-call-engineer",
            )

    # ------------------------------------------------------------------
    # 全链路追踪
    # ------------------------------------------------------------------

    def test_full_lifecycle_traceability(self):
        """一条候选清单 → 数据集 → 训练 → 模型 → Shadow → Canary → Production
        的全链路审计踪迹必须完整且不可变。"""
        lifecycle = self.lifecycle

        # 1. 候选样本审批
        audit_before = len(lifecycle.get_audit_trail())
        self.assertGreater(audit_before, 0)

        # 2. 创建并审批数据集
        lifecycle.create_dataset_version(
            DATASET_VERSION_ID,
            DATASET_ID,
            CANDIDATE_MANIFEST_ID,
            "retraining-v2.0",
            "ml-engineer-1",
        )
        lifecycle.approve_dataset_version(DATASET_VERSION_ID, "quality-lead")

        # 3. 训练
        run = lifecycle.create_training_run(
            DATASET_VERSION_ID,
            "config-v3.1",
            None,
            "ml-engineer-1",
        )
        run_id = run["training_run_id"]
        lifecycle.mark_training_running(run_id)
        lifecycle.complete_training_run(
            run_id,
            TRAINING_OUTPUT_HASH,
            {"mAP": 0.91},
        )

        # 4. 注册与验证
        lifecycle.register_model(MODEL_VERSION_ID, run_id, "ml-engineer-1")
        lifecycle.submit_validation_decision(
            MODEL_VERSION_ID,
            "APPROVE",
            "精度满足 P1 门禁要求",
            EVALUATION_REPORT_SHA256,
            "quality-lead",
        )

        # 5. Shadow
        lifecycle.create_deployment(
            DEPLOYMENT_ID_SHADOW,
            MODEL_VERSION_ID,
            "SHADOW",
            "STATION",
            [STATION_IDS[0]],
            0.0,
            MODEL_VERSION_ID,
            "deployer-1",
        )
        lifecycle.approve_deployment(DEPLOYMENT_ID_SHADOW, "QUALITY_APPROVER", "APPROVE", "ok", "quality-lead")
        lifecycle.approve_deployment(DEPLOYMENT_ID_SHADOW, "MODEL_RELEASE_APPROVER", "APPROVE", "ok", "release-manager")
        lifecycle.activate_deployment(DEPLOYMENT_ID_SHADOW)

        # 6. Canary
        lifecycle.create_deployment(
            DEPLOYMENT_ID_CANARY,
            MODEL_VERSION_ID,
            "CANARY",
            "PERCENTAGE",
            STATION_IDS,
            0.1,
            MODEL_VERSION_ID,
            "deployer-1",
        )
        lifecycle.approve_deployment(DEPLOYMENT_ID_CANARY, "QUALITY_APPROVER", "APPROVE", "ok", "quality-lead")
        lifecycle.approve_deployment(DEPLOYMENT_ID_CANARY, "MODEL_RELEASE_APPROVER", "APPROVE", "ok", "release-manager")
        lifecycle.activate_deployment(DEPLOYMENT_ID_CANARY)

        # 7. Production
        lifecycle.create_deployment(
            DEPLOYMENT_ID_PRODUCTION,
            MODEL_VERSION_ID,
            "PRODUCTION",
            "STATION",
            STATION_IDS,
            1.0,
            MODEL_VERSION_ID,
            "deployer-1",
        )
        lifecycle.approve_deployment(DEPLOYMENT_ID_PRODUCTION, "QUALITY_APPROVER", "APPROVE", "ok", "quality-lead")
        lifecycle.approve_deployment(DEPLOYMENT_ID_PRODUCTION, "MODEL_RELEASE_APPROVER", "APPROVE", "ok", "release-manager")
        lifecycle.activate_deployment(DEPLOYMENT_ID_PRODUCTION)

        # 验证全链路审计
        audit = lifecycle.get_audit_trail()
        expected_events = [
            "CANDIDATE_APPROVED",
            "DATASET_VERSION_CREATED",
            "DATASET_VERSION_APPROVED",
            "TRAINING_RUN_CREATED",
            "TRAINING_RUN_STARTED",
            "TRAINING_RUN_COMPLETED",
            "MODEL_REGISTERED",
            "VALIDATION_DECIDED",
            "DEPLOYMENT_CREATED",
            "DEPLOYMENT_APPROVED",
            "DEPLOYMENT_APPROVED",
            "DEPLOYMENT_ACTIVATED",
            "DEPLOYMENT_CREATED",
            "DEPLOYMENT_APPROVED",
            "DEPLOYMENT_APPROVED",
            "DEPLOYMENT_ACTIVATED",
            "DEPLOYMENT_CREATED",
            "DEPLOYMENT_APPROVED",
            "DEPLOYMENT_APPROVED",
            "DEPLOYMENT_ACTIVATED",
        ]
        actual_events = [e["event"] for e in audit]
        self.assertEqual(expected_events, actual_events)

        # 验证每条审计记录都有必要字段
        for entry in audit:
            self.assertIn("event", entry)
            self.assertIn("entity_id", entry)
            self.assertIn("actor", entry)
            self.assertIn("timestamp", entry)
            self.assertIn("sequence", entry)
            self.assertIsInstance(entry["sequence"], int)

        # 序列号单调递增
        sequences = [e["sequence"] for e in audit]
        self.assertEqual(sequences, sorted(sequences))
        self.assertEqual(sequences, list(range(1, len(sequences) + 1)))

        # 按实体过滤审计踪迹
        model_audit = lifecycle.get_audit_trail(MODEL_VERSION_ID)
        model_events = [e["event"] for e in model_audit]
        self.assertIn("MODEL_REGISTERED", model_events)
        self.assertIn("VALIDATION_DECIDED", model_events)

        # 验证实体间引用链
        model = lifecycle.get_model_version(MODEL_VERSION_ID)
        self.assertEqual(run_id, model["training_run_id"])

        training = lifecycle.get_training_run(run_id)
        self.assertEqual(DATASET_VERSION_ID, training["dataset_version_id"])

        dataset = lifecycle.get_dataset_version(DATASET_VERSION_ID)
        self.assertEqual(CANDIDATE_MANIFEST_ID, dataset["candidate_manifest_id"])

        # 所有部署引用同一模型版本
        for dep_id in (DEPLOYMENT_ID_SHADOW, DEPLOYMENT_ID_CANARY, DEPLOYMENT_ID_PRODUCTION):
            dep = lifecycle.get_deployment(dep_id)
            self.assertEqual(MODEL_VERSION_ID, dep.model_version_id)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _prepare_approved_dataset(self):
        self.lifecycle.create_dataset_version(
            DATASET_VERSION_ID,
            DATASET_ID,
            CANDIDATE_MANIFEST_ID,
            "retraining-v2.0",
            "ml-engineer-1",
        )
        self.lifecycle.approve_dataset_version(DATASET_VERSION_ID, "quality-lead")

    def _prepare_completed_training(self):
        self._prepare_approved_dataset()
        self._run_id = self.lifecycle.create_training_run(
            DATASET_VERSION_ID,
            "config-v3.1",
            None,
            "ml-engineer-1",
        )["training_run_id"]
        self.lifecycle.mark_training_running(self._run_id)
        self.lifecycle.complete_training_run(
            self._run_id,
            TRAINING_OUTPUT_HASH,
            {"mAP": 0.91, "loss": 0.12},
        )
        return self._run_id

    def _prepare_approved_model_v2(self):
        """使用独立的 training run 注册 v2 模型。"""
        self.lifecycle.create_dataset_version(
            "dsv-v2",
            DATASET_ID,
            CANDIDATE_MANIFEST_ID,
            "retraining-v2.1",
            "ml-engineer-2",
        )
        self.lifecycle.approve_dataset_version("dsv-v2", "quality-lead")
        run_v2 = self.lifecycle.create_training_run("dsv-v2", "config-v4.0", MODEL_VERSION_ID, "ml-engineer-2")
        run_v2_id = run_v2["training_run_id"]
        self.lifecycle.mark_training_running(run_v2_id)
        self.lifecycle.complete_training_run(run_v2_id, TRAINING_OUTPUT_HASH_V2, {"mAP": 0.89})

        self.lifecycle.register_model(MODEL_VERSION_ID_V2, run_v2_id, "ml-engineer-2")
        self.lifecycle.submit_validation_decision(
            MODEL_VERSION_ID_V2,
            "APPROVE",
            "v2 审批通过",
            EVALUATION_REPORT_SHA256,
            "quality-lead",
        )

    def _create_and_activate_deployment(self, deployment_id, environment):
        self.lifecycle.create_deployment(
            deployment_id,
            MODEL_VERSION_ID,
            environment,
            "STATION" if environment != "CANARY" else "PERCENTAGE",
            STATION_IDS if environment != "SHADOW" else [STATION_IDS[0]],
            0.1 if environment == "CANARY" else (1.0 if environment == "PRODUCTION" else 0.0),
            MODEL_VERSION_ID,
            "deployer-1",
        )
        self.lifecycle.approve_deployment(deployment_id, "QUALITY_APPROVER", "APPROVE", "ok", "quality-lead")
        self.lifecycle.approve_deployment(deployment_id, "MODEL_RELEASE_APPROVER", "APPROVE", "ok", "release-manager")
        return self.lifecycle.activate_deployment(deployment_id)


# ------------------------------------------------------------------
# 契约一致性测试
# ------------------------------------------------------------------


class MlopsContractConsistencyTests(unittest.TestCase):

    def test_contract_exposes_all_mlops_lifecycle_operations(self):
        import json
        from pathlib import Path

        ROOT = Path(__file__).resolve().parents[3]
        contract = json.loads(
            (ROOT / "contracts/openapi/tool-defect-api-v1.json").read_text(encoding="utf-8")
        )
        mlops_operations = {
            operation["operationId"]
            for path, methods in contract["paths"].items()
            for method, operation in methods.items()
            if isinstance(operation, dict)
            and "tags" in operation
            and "mlops" in operation["tags"]
        }
        required = {
            "createDatasetVersion",
            "getDatasetVersion",
            "createTrainingRun",
            "getTrainingRun",
            "submitModelValidationDecision",
            "createModelDeployment",
            "approveModelDeployment",
            "rollbackModelDeployment",
        }
        self.assertTrue(
            required.issubset(mlops_operations),
            f"契约缺少 MLOps 操作: {required - mlops_operations}",
        )

    def test_model_status_transitions_are_valid(self):
        import json
        from pathlib import Path

        ROOT = Path(__file__).resolve().parents[3]
        schema = json.loads(
            (ROOT / "contracts/json-schema/common-v1.schema.json").read_text(encoding="utf-8")
        )
        valid_statuses = set(schema["$defs"]["ModelStatus"]["enum"])

        expected = {
            "DRAFT",
            "VALIDATING",
            "APPROVED",
            "SHADOW",
            "CANARY",
            "PRODUCTION",
            "REJECTED",
            "QUARANTINED",
            "RETIRED",
        }
        self.assertEqual(expected, valid_statuses)

    def test_deployment_environments_match_contract(self):
        import json
        from pathlib import Path

        ROOT = Path(__file__).resolve().parents[3]
        contract = json.loads(
            (ROOT / "contracts/openapi/tool-defect-api-v1.json").read_text(encoding="utf-8")
        )
        deployment_schema = contract["components"]["schemas"]["ModelDeploymentCreateRequest"]
        valid_environments = set(deployment_schema["properties"]["environment"]["enum"])

        self.assertEqual({"SHADOW", "CANARY", "PRODUCTION"}, valid_environments)


if __name__ == "__main__":
    unittest.main()
