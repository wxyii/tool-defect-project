# 数据集构建任务

本目录包含两类入口：

- `build.py`：离线生成带准入证据、去重和泄漏检查的候选清单包；
- `worker.py`：常驻领取业务库中的 `BUILDING` 版本，读取对象存储中的已批准
  候选清单，复核哈希、样本数、字段、重复内容和组级划分，随后推进到
  `VALIDATING` 或明确 `REJECTED`。

开发环境通过 `./tools/dev/start-all.sh` 自动启动 `worker.py`，其日志位于
`.build/dev-runtime/dataset-builder.log`。执行端使用有期限的数据库领取事实；
进程异常退出后，任务可在租约到期后由新的执行端重新领取。

执行端不会批准或冻结版本。`VALIDATING → FROZEN` 仍必须由具有数据集审批权限的
独立用户在业务接口或网页控制台完成。
