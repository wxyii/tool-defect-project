# 三组历史双任务模型技术评估

本任务实现 `P2-A04`：三组候选分别加载、分别评估，禁止跨目录混配结构与权重。评估只产生 `TEST_CANDIDATE` 证据，不能据此声明生产可用。

模型源优先使用设计文档约定的 `outputs/training/`。迁移前资产若只存在于项目根 `training/`，评估器将其作为只读迁移暂存来源，并在报告中记录实际相对路径；不会复制、移动或混配模型文件。

固定比较集来自 `data/manifests/retrain.csv` 的 34 个测试样本。对于自适应环形和边界归一化候选，评估器按这 34 个样本标识从各自预处理清单生成候选专属派生清单，保留各自图片与掩膜路径并锁定相同顺序；冻结的 `data/` 不会被修改。

统一验证命令：

```shell
make verify-models
```

受控输出位于 `controlled-output/p2-baseline/`：

- `evaluation-report.json`：候选哈希、派生清单哈希、汇总指标、置信区间和资源记录。
- `failure-list.json`：缺失模型、哈希冲突、清单冲突或评估失败清单。
- `evaluation-manifests/`：三份由冻结 34 图基线派生的候选专属输入清单。
- `<candidate>/predictions.csv`：按固定顺序生成的逐图分类与分割结果。

任何模型文件缺失、哈希不符、测试样本不完整或评估异常都会返回 `BLOCKED`，且不会生成生产通过声明。

P6-05/P6-06 严格验证：

- `verify_p6_05.py` 重新验签模型包，核对 SBOM、训练/数据集/评估绑定、双角色审批和不可变别名。
- `verify_p6_06.py` 检查双槽验签预热、影子、灰度、正式切换、失败摘流和真实回滚记录。

```shell
make verify-p6-05
make verify-p6-06
```

P6-08/G6 严格验证：

- `verify_p6_08.py` 只接受真实 business-api、inference-service、PostgreSQL 和对象存储共同生成的候选—数据集—训练—模型—部署—回滚证据；内存状态机、模拟器、干跑和缺失反查链路均阻塞。
- `verify_g6.py` 检查 `Docs/reports/P6-gate-acceptance.json` 是否包含 v1、八项 P6 全部真实 `PASS` 证据和不可变标记；缺少汇总或任一任务未通过均返回 2。

```shell
make verify-p6-08
make verify-g6
```
