# 开发环境

复制 `.env.example` 到工作区外的受限密钥文件并填写随机值，再显式传入：

```sh
docker compose --env-file /受限路径/tool-defect-development.env \
  -f deploy/compose/development.yml up -d
```

示例文件不含可用凭据。Compose 使用 `${变量:?说明}` 强制注入，所有端口仅绑定
本机。测试替身包括 PostgreSQL、RabbitMQ、S3 兼容对象存储及遥测、指标与看板。
