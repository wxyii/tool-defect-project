# P6-03 训练流水线任务

`train.py` 是作业编排入口，实际 TensorFlow 双输出模型训练复用
`src/tool_defect/training/retrain_multitask.py`。入口会锁定数据集版本、清单哈希、
初始化模型哈希、配置、环境、代码工作树、随机种子和两阶段设置；支持同一运行恢复，
配置或输入哈希变化必须新建运行。

入口拒绝覆盖已有运行，不删除 `controlled-output`。训练失败会留下
`failure.json` 和 `BLOCKED` 报告；文本指标或空文件不能作为检查点。资源隔离只有在
平台注入 `TOOL_DEFECT_RESOURCE_ISOLATION=ENFORCED` 时才记录为 `ENFORCED`，本地声明
不会被严格门禁当作通过。

统一验证命令：

```shell
make verify-p6-03
```
