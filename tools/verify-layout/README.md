# 仓库和环境验证

- `verify_layout.py` 校验目录、所有权、禁止文件、统一入口和跨模块依赖。
- `check_environment.py source` 只检查离线源码门禁所需工具。
- `check_environment.py strict` 检查完整 P1 工具链，任何缺失都会失败。
- `run_target.py` 承载统一测试入口；任务未实现、测试为空或工具缺失时返回非零。
