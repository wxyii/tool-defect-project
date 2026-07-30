# P5 分级运行手册

本目录是 P5 的受控故障处置入口。S1 表示数据安全、生产判定或核心恢复能力已中断；S2 表示能力降级且存在积压风险；S3 表示有余量的预警。状态未知、证据不完整或恢复验证失败时，检测与处置保持 `HOLD`。

执行者先读对应手册，只做只读检查；涉及回灌、清理、切换、恢复或回滚时，必须具备手册列明的权限，填写操作原因，完成二次确认并记录审计事件。不得因为告警暂时消失就宣告恢复。

| 场景 | 手册 | 默认级别 |
|---|---|---|
| 磁盘满或高水位 | [01-disk-full.md](01-disk-full.md) | S1 |
| 采集端或服务网络中断 | [02-network-outage.md](02-network-outage.md) | S2 |
| 死信与有界重试耗尽 | [03-dead-letter.md](03-dead-letter.md) | S2 |
| 数据库不可写 | [04-database-unwritable.md](04-database-unwritable.md) | S1 |
| 对象存储不可用或完整性异常 | [05-object-storage.md](05-object-storage.md) | S1 |
| 生产模型无就绪实例 | [06-model-not-ready.md](06-model-not-ready.md) | S1 |
| 图片、模型或清单哈希冲突 | [07-hash-conflict.md](07-hash-conflict.md) | S1 |
| 人工复核积压 | [08-review-backlog.md](08-review-backlog.md) | S2 |
| 联合备份与隔离恢复 | [09-backup-restore.md](09-backup-restore.md) | S1 |
| 紧急版本回滚 | [10-emergency-rollback.md](10-emergency-rollback.md) | S1 |

自动化独立执行器的演练证据见 `drill-record.json`；该记录不替代 P7 由未参与开发人员在真实环境完成的现场演练。
