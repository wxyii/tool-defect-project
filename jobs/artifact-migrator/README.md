# 制品迁移任务（P6-01）

迁移必须按数量、总字节和 SHA-256 对账，不删除来源目录，不混配历史版本。迁移器只
写入新的受控输出目录；目标目录已有内容时会拒绝覆盖，防止不可变版本被静默重建。

## 命令边界

先在新的临时受控目录生成清单和源目录快照：

```text
python jobs/artifact-migrator/migrate.py --output-dir <new-controlled-output>
```

对象、备份和恢复根目录必须由外部受控流程准备，命令本身不复制或删除对象，只登记
并重算实际文件：

```text
python jobs/artifact-migrator/register_objects.py \
  --output-root <new-controlled-output> \
  --object-root <mounted-object-root> \
  --backup-root <mounted-backup-root> \
  --restore-root <isolated-restore-root>
```

统一只读门禁为：

```text
make verify-p6-01
```

缺少独立对象根目录、备份/恢复根目录、源快照或正式独立审批时，门禁必须返回非零
并保持 `BLOCKED`；不能用本地源目录、自动生成的 `DRAFT` 或空目录冒充通过。
