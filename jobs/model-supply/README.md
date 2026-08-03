# R8 模型供应链验证

本目录承载 R8-02 的隔离模型包验证入口。验证器只检查压缩包边界、路径、特殊文件、压缩比、大小、内层哈希清单、模型清单和 Ed25519 签名；它不加载模型、不执行包内代码、不访问业务数据库，也不把验证结果写成生产启用状态。

当前实现刻意不修改 `contracts/`、三语言生成包或数据库迁移。R7 尚未交接时，R8 的上传会话、模型版本来源快照、启用申请和回退事实仍需在串行窗口中接入业务后端。

本地单元验证：

```text
PYTHONPATH=src .venv/bin/python -m unittest discover -s jobs/model-supply/tests -p 'test_*.py'
```

真实门禁仍需由根 `Makefile` 在 R7 交接后接入 `verify_model_supply.py`，并提供批准的隔离配置、固定测试集、验证运行身份和信任根。缺少这些前置时必须失败或 `HOLD`。
