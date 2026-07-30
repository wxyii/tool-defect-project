# 仓库和环境验证

- `verify_layout.py` 校验目录、所有权、禁止文件、统一入口和跨模块依赖。
- `check_environment.py source` 只检查离线源码门禁所需工具。
- `check_environment.py strict` 检查完整 P1 工具链，任何缺失都会失败。
- `run_target.py` 承载统一测试入口；任务未实现、测试为空或工具缺失时返回非零。
- `make verify-all` 当前汇总 P0–P2 必需门禁。P3 以后的集成、端到端、故障和性能入口继续保留，只有在对应阶段实现后才能加入汇总；直接调用未实现入口仍必须失败。
