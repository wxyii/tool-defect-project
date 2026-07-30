# 开发环境

复制 `.env.example` 到工作区外的受限密钥文件并填写随机值，再显式传入：

```sh
docker compose --env-file /受限路径/tool-defect-development.env \
  -f deploy/compose/development.yml up -d
```

示例文件不含可用凭据。Compose 使用 `${变量:?说明}` 强制注入，所有端口仅绑定
本机。测试替身包括 PostgreSQL、RabbitMQ、S3 兼容对象存储及遥测、指标与看板。

PostgreSQL 固定为 18.4。官方镜像从 18 起把默认 `PGDATA` 调整为
`/var/lib/postgresql/18/docker`，因此 Compose 将独立的 `postgres-data-v18`
卷挂载到 `/var/lib/postgresql`。旧的 PostgreSQL 17 开发卷不会被自动删除或
原地升级；如需保留旧数据，须先备份并按 PostgreSQL 主版本升级流程迁移。
