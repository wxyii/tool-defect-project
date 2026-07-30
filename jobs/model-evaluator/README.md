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
